"""
Background worker for processing uploaded files using Task Manager
"""

import os
import time
import logging
import uuid
import threading
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import pandas as pd

from .task_manager import TaskManager, TaskPriority, TaskStatus
from service.azure_ai_search import AzureAISearchService
from service.blob_storage import BlobStorageService
from service.indexer import IngestionIndexer
from service.llm_client import EmbeddingClient
from config import Config


logger = logging.getLogger("main")
BACKEND_EXCEPTION_TAG = "BACKEND_EXCEPTION"


class FileProcessor:
    """Background worker for processing uploaded files using TaskManager"""

    def __init__(
        self,
        temp_dir: str = "temp_uploads",
        max_workers: int = 1,
        cleanup_interval: int = 300,
        file_age_threshold: int = 3600,
        connection_manager=None,
    ):
        self.temp_dir = temp_dir
        self.task_manager = TaskManager(max_workers=max_workers)
        self.orchestrator = None
        self.connection_manager = connection_manager  # For WebSocket updates

        # Store metadata in memory (uploaded via /v1/upload-metadata)
        self.metadata_df = None  # pandas DataFrame with metadata
        self.metadata_timestamp = None  # When it was uploaded

        # Initialize Azure services immediately (not lazy)
        self.search_service = None
        self.blob_service = None
        self.indexer = None
        self.llm_client = None

        # Track initialization status
        self.azure_services_initialized = False

        # Worker-specific file list storage (server-side only)
        self.worker_file_lists = {}  # Dict to store per-worker file lists in memory
        self.worker_file_lists_lock = threading.Lock()  # Lock for thread-safe access
        self.worker_file_lists_dir = os.path.join(
            temp_dir, "worker_file_lists"
        )  # Directory for worker JSON files
        os.makedirs(
            self.worker_file_lists_dir, exist_ok=True
        )  # Create directory for worker files

        # Merge state tracking to prevent race conditions
        self.merge_in_progress = False  # Flag to prevent concurrent merges
        self.merge_lock = threading.Lock()  # Lock for merge operations

        # File list update lock to prevent race conditions when updating blob storage
        self.file_list_update_lock = threading.Lock()  # Lock for file list updates

        # Cleanup manager settings
        self.cleanup_interval = (
            cleanup_interval  # seconds between cleanup runs (default: 5 minutes)
        )
        self.file_age_threshold = file_age_threshold  # seconds before file can be cleaned up (default: 1 hour)
        self.cleanup_thread = None
        self.cleanup_running = False
        self.config = Config()
        # Ensure temp directory exists
        os.makedirs(temp_dir, exist_ok=True)

        # Initialize Azure services immediately for accurate health checks
        try:
            self._initialize_azure_services()
        except Exception as e:
            logger.exception(
                "[ERROR] [INIT ERROR] Azure services initialization failed during startup: %s",
                e,
            )
            logger.warning(
                "[WARNING] [INIT WARNING] Services will remain uninitialized - health checks will test connectivity directly"
            )

    def start(self):
        """Start the background worker - TaskManager automatically starts workers"""
        self.start_cleanup_manager()

    def set_metadata(self, df: pd.DataFrame, timestamp: str = None):
        """
        Set the current metadata DataFrame to use for file processing.
        Called by /v1/upload-metadata endpoint after validation.

        Args:
            df: Validated pandas DataFrame with metadata
            timestamp: Optional timestamp string for tracking
        """
        self.metadata_df = df
        self.metadata_timestamp = timestamp or datetime.now().strftime("%Y%m%d%H%M%S")

        # Log sample data for debugging
        if len(df) > 0:
            logger.debug(f"[DEBUG] [METADATA SET] Sample row data: {df.iloc[0].to_dict()}")
            logger.debug(
                f"[DEBUG] [METADATA SET] Unique files in metadata: {df['file_name'].nunique() if 'file_name' in df.columns else 'N/A'}"
            )
            logger.debug(
                f"[DEBUG] [METADATA SET] Unique files in metadata: {df['file_name'].nunique() if 'file_name' in df.columns else 'N/A'}"
            )

    def get_metadata_info(self):
        """Get information about currently loaded metadata"""
        if self.metadata_df is None:
            return {
                "loaded": False,
                "message": "No metadata loaded. Upload a metadata file first.",
            }

        return {
            "loaded": True,
            "rows": len(self.metadata_df),
            "columns": list(self.metadata_df.columns),
            "timestamp": self.metadata_timestamp,
        }

    def stop(self):
        """Stop the background worker"""
        self.stop_cleanup_manager()
        self.task_manager.shutdown(wait=True, timeout=30)

    def create_upload_record(
        self,
        original_filename: str,
        file_path: str,
        file_size: int,
        bot_id: str = None,
        metadata: dict = None,
    ) -> str:
        """Create a new upload record using task manager and return work_id"""
        work_id = str(uuid.uuid4())

        # Use config bot_id if not provided
        if not bot_id:
            config = Config()
            bot_id = config.bot_id

        # Add processing task to task manager
        self.task_manager.add_task(
            description=f"Process file: {original_filename}",
            function=self._process_file_task,
            args=(work_id, original_filename, file_path, file_size, bot_id, metadata),
            priority=TaskPriority.NORMAL,
            work_id=work_id,
            original_filename=original_filename,
            file_path=file_path,
            file_size=file_size,
        )

        return work_id

    def get_upload_info(self, work_id: str) -> Optional[Dict[str, Any]]:
        """Get upload information by work_id"""
        task = self.task_manager.get_task_by_work_id(work_id)
        if not task:
            return None

        # Convert task status to the expected format
        status_mapping = {
            TaskStatus.PENDING: "queued",
            TaskStatus.IN_PROGRESS: "processing",
            TaskStatus.DONE: "completed",
            TaskStatus.FAILED: "failed",
        }

        result = {
            "work_id": work_id,
            "original_filename": task.original_filename,
            "file_path": task.file_path,
            "file_size": task.file_size,
            "status": status_mapping.get(task.status, "unknown"),
            "created_at": task.created_at.isoformat(),
            "started_processing_at": (
                task.started_at.isoformat() if task.started_at else None
            ),
            "completed_at": (
                task.completed_at.isoformat() if task.completed_at else None
            ),
            "error_message": task.error,
            "progress_percentage": task.progress_percentage,
            "metadata": task.metadata or {},
        }

        # Add current message if available in metadata
        if task.metadata and "current_message" in task.metadata:
            result["current_message"] = task.metadata["current_message"]

        return result

    def get_uploads_by_status(self, status: str) -> list:
        """Get all uploads with a specific status"""
        tasks = []

        if status == "queued":
            tasks = self.task_manager.get_pending_tasks()
        elif status == "processing":
            tasks = self.task_manager.get_in_progress_tasks()
        elif status == "completed":
            tasks = self.task_manager.get_done_tasks()
        elif status == "failed":
            tasks = self.task_manager.get_failed_tasks()

        # Convert to expected format
        uploads = []
        status_mapping = {
            TaskStatus.PENDING: "queued",
            TaskStatus.IN_PROGRESS: "processing",
            TaskStatus.DONE: "completed",
            TaskStatus.FAILED: "failed",
        }

        for task in tasks:
            if task.work_id:  # Only include file processing tasks
                uploads.append(
                    {
                        "work_id": task.work_id,
                        "original_filename": task.original_filename,
                        "file_path": task.file_path,
                        "file_size": task.file_size,
                        "status": status_mapping.get(task.status, "unknown"),
                        "created_at": task.created_at.isoformat(),
                        "started_processing_at": (
                            task.started_at.isoformat() if task.started_at else None
                        ),
                        "completed_at": (
                            task.completed_at.isoformat() if task.completed_at else None
                        ),
                        "error_message": task.error,
                        "progress_percentage": task.progress_percentage,
                        "metadata": task.metadata or {},
                    }
                )

        return uploads

    def update_status(self, work_id: str, status: str, progress_percentage: int = None):
        """Update task status and progress"""
        task = self.task_manager.get_task_by_work_id(work_id)
        if task and progress_percentage is not None:
            self.task_manager.update_task_progress(task.id, progress_percentage)

    def get_processing_statistics(self) -> Dict[str, Any]:
        """Get processing statistics from task manager"""
        stats = self.task_manager.get_statistics()

        # Count only file processing tasks
        file_tasks_pending = len(
            [t for t in self.task_manager.get_pending_tasks() if t.work_id]
        )
        file_tasks_processing = len(
            [t for t in self.task_manager.get_in_progress_tasks() if t.work_id]
        )
        file_tasks_completed = len(
            [t for t in self.task_manager.get_done_tasks() if t.work_id]
        )
        file_tasks_failed = len(
            [t for t in self.task_manager.get_failed_tasks() if t.work_id]
        )

        total_files = (
            file_tasks_pending
            + file_tasks_processing
            + file_tasks_completed
            + file_tasks_failed
        )
        progress = (
            ((file_tasks_completed + file_tasks_failed) / total_files * 100)
            if total_files > 0
            else 100
        )

        return {
            "total": total_files,
            "queued": file_tasks_pending,
            "processing": file_tasks_processing,
            "completed": file_tasks_completed,
            "failed": file_tasks_failed,
            "overall_progress": progress,
            "worker_stats": {
                "max_workers": stats["workers"],
                "active_workers": stats["active_workers"],
                "total_tasks_added": stats["total_added"],
                "total_tasks_completed": stats["total_completed"],
                "total_tasks_failed": stats["total_failed"],
            },
        }

    def cleanup_old_uploads(self, days: int = 7):
        """Clean up old completed/failed tasks"""
        # Get tasks older than specified days
        cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)

        cleaned_count = 0
        for task_dict in [self.task_manager._done, self.task_manager._failed]:
            tasks_to_remove = []
            for task_id, task in task_dict.items():
                if task.completed_at and task.completed_at.timestamp() < cutoff_time:
                    tasks_to_remove.append(task_id)

            for task_id in tasks_to_remove:
                del task_dict[task_id]
                cleaned_count += 1
        return cleaned_count

    def _update_file_list_in_blob(
        self,
        filename: str,
        file_size: int,
        file_uri: str = None,
        bot_id: str = None,
        csv_metadata: pd.Series = None,
    ):
        """
        Update the file list in blob storage directly after each file is processed.

        Args:
            filename: Name of the processed file
            file_size: Size of the file in bytes
            file_uri: Optional URI to the file in blob storage
            bot_id: Bot ID to use (if not provided, will use config bot_id)
            csv_metadata: CSV metadata row from Excel spreadsheet for this file
        """

        # Use lock to prevent race conditions with concurrent file uploads
        with self.file_list_update_lock:
            try:
                if not self.blob_service:
                    logger.error(
                        "[ERROR] [FILE LIST UPDATE] Blob service not available, skipping file list update"
                    )
                    return

                # Use provided bot_id or fall back to config
                if not bot_id:
                    config = Config()
                    bot_id = config.bot_id
                else:
                    pass
                file_list_name = f"{bot_id}-filelist.json"

                # Get current timestamp
                timestamp = datetime.now().isoformat()

                # Try to download existing file list from blob storage
                existing_file_list = {
                    "BotID": bot_id,
                    "files": [],
                    "updated_at": timestamp,
                }

                try:
                    existing_content = self.blob_service.download_bytes(file_list_name)
                    if existing_content:
                        existing_file_list = json.loads(
                            existing_content.decode("utf-8")
                        )
                    else:
                        pass
                except Exception as download_ex:
                    if "BlobNotFound" in str(download_ex) or "404" in str(download_ex):
                        logger.info(
                            "[INFO] [FILE LIST] No existing file list found, creating new one"
                        )
                    else:
                        logger.warning(
                            f"[WARNING] [FILE LIST] Could not download existing file list: {download_ex}"
                        )

                # Create new file entry
                config = Config()
                new_file_entry = {
                    "name": filename,
                    "file_name": filename,
                    "size": file_size,
                    "file_uri": file_uri
                    or f"https://{config.azure_storage_account_name}.blob.core.windows.net/{config.azure_storage_container_name}/{filename}",
                    "uploaded_at": timestamp,
                    "processed_at": timestamp,
                    "status": "completed",
                    "content_type": self._get_content_type(filename),
                }

                # Add CSV metadata from Excel spreadsheet if provided
                if csv_metadata is not None:
                    metadata_dict = {}
                    for key, value in csv_metadata.items():
                        # Skip the file_name field as it's already stored in the main file entry
                        if key.lower() == "file_name":
                            continue
                        if pd.notna(value):
                            metadata_dict[key] = (
                                str(value).strip() if str(value).strip() else ""
                            )
                        else:
                            metadata_dict[key] = ""

                    if metadata_dict:
                        new_file_entry["metadata"] = metadata_dict

                # Update or add the file entry
                files = existing_file_list.get("files", [])
                file_exists = False

                for i, existing_file in enumerate(files):
                    if (
                        existing_file.get("name") == filename
                        or existing_file.get("file_name") == filename
                    ):
                        # Update existing file entry
                        files[i] = new_file_entry
                        file_exists = True
                        break

                if not file_exists:
                    files.append(new_file_entry)

                # Update file list metadata
                existing_file_list["files"] = files
                existing_file_list["updated_at"] = timestamp
                existing_file_list["total_files"] = len(files)
                existing_file_list["BotID"] = bot_id

                # Upload updated file list to blob storage
                json_content = json.dumps(existing_file_list, indent=2).encode("utf-8")
                self.blob_service.upload_bytes(
                    file_list_name, json_content, content_type="application/json"
                )

            except Exception as e:
                logger.exception("[ERROR] [FILE LIST] Error updating file list: %s", e)

    def _check_and_merge_if_all_done(self, bot_id: str = None):
        """
        Check if all tasks are complete and trigger merge if this is the last task.
        This is called after each file completes processing.

        Args:
            bot_id: Bot ID to use for merging
        """
        try:
            # Get statistics from task manager
            stats = self.task_manager.get_statistics()
            in_progress_count = stats.get("tasks", {}).get("in_progress", 0)
            pending_count = stats.get("tasks", {}).get("pending", 0)

            # If no tasks are pending or in progress, trigger merge
            if in_progress_count == 0 and pending_count == 0:
                # Use lock to prevent race condition where multiple threads try to merge simultaneously
                with self.merge_lock:
                    # Check again inside lock to ensure another thread hasn't already started merge
                    if self.merge_in_progress:
                        return

                    # Check if there are any worker files to merge
                    worker_files = [
                        f
                        for f in os.listdir(self.worker_file_lists_dir)
                        if f.endswith(".json") and "worker" in f
                    ]

                    if worker_files:
                        self.merge_in_progress = True  # Set flag before merging
                        try:
                            self.merge_worker_file_lists(bot_id)
                        finally:
                            self.merge_in_progress = (
                                False  # Clear flag after merge completes or fails
                            )
                    else:
                        logger.info("[INFO] [AUTO-MERGE] No worker files found to merge")
            else:
                logger.debug(
                    f"[DEBUG] [AUTO-MERGE] Still waiting - {pending_count + in_progress_count} tasks remaining"
                )

        except Exception as e:
            logger.exception(
                "[ERROR] [AUTO-MERGE ERROR] Failed to check/trigger automatic merge: %s",
                e,
            )
            # Make sure to clear the flag if an error occurs
            with self.merge_lock:
                self.merge_in_progress = False

    def merge_worker_file_lists(self, bot_id: str = None) -> Dict[str, Any]:
        """
        Merge all worker-specific file lists into one final file list.
        This should be called after all files have been processed.

        Args:
            bot_id: Bot ID to use (if not provided, will use config bot_id)

        Returns:
            Dictionary with merge statistics and final file list info
        """

        try:
            # Use provided bot_id or fall back to config
            if not bot_id:
                config = Config()
                bot_id = config.bot_id
            # Get current timestamp
            timestamp = datetime.now().isoformat()

            # Collect all files from worker lists
            all_files = []
            worker_stats = {}

            # First, load all worker JSON files from disk to ensure we have everything
            worker_files_on_disk = [
                f
                for f in os.listdir(self.worker_file_lists_dir)
                if f.endswith(".json") and f.startswith(f"{bot_id}-filelist-worker-")
            ]

            for worker_file in worker_files_on_disk:
                try:
                    worker_file_path = os.path.join(
                        self.worker_file_lists_dir, worker_file
                    )
                    with open(worker_file_path, "r") as f:
                        worker_data = json.load(f)
                        worker_id = worker_data.get("worker_id", "unknown")
                        worker_files = worker_data.get("files", [])

                        all_files.extend(worker_files)
                        worker_stats[worker_id] = {
                            "file_count": len(worker_files),
                            "created_at": worker_data.get("created_at"),
                            "updated_at": worker_data.get("updated_at"),
                        }

                except Exception as load_ex:
                    logger.exception(
                        "[ERROR] [MERGE] Failed to load worker file %s: %s",
                        worker_file,
                        load_ex,
                    )

            # Remove duplicates (keep the latest version based on processed_at)
            unique_files = {}
            for file_entry in all_files:
                filename = file_entry.get("name") or file_entry.get("file_name")
                if filename:
                    # Keep the file with the latest processed_at timestamp
                    if filename not in unique_files:
                        unique_files[filename] = file_entry
                    else:
                        existing_timestamp = unique_files[filename].get(
                            "processed_at", ""
                        )
                        new_timestamp = file_entry.get("processed_at", "")
                        if new_timestamp > existing_timestamp:
                            unique_files[filename] = file_entry

            final_files_list = list(unique_files.values())

            # Create the merged file list data
            merged_data = {
                "bot_id": bot_id,
                "updated_at": timestamp,
                "updated_by": "background_processor_merge",
                "total_files": len(final_files_list),
                "merge_info": {
                    "merged_at": timestamp,
                    "worker_count": len(worker_stats),
                    "total_entries_processed": len(all_files),
                    "unique_files": len(final_files_list),
                    "duplicates_removed": len(all_files) - len(final_files_list),
                    "worker_stats": worker_stats,
                },
                "files": final_files_list,
            }

            # Upload the merged file list to blob storage
            if self.blob_service:
                try:
                    file_list_name = f"{bot_id}-filelist.json"
                    json_content = json.dumps(merged_data, indent=2).encode("utf-8")
                    self.blob_service.upload_bytes(file_list_name, json_content)

                except Exception as blob_ex:
                    logger.error(
                        f"[ERROR] [MERGE] Failed to upload merged file list to blob: {blob_ex}"
                    )
                    raise
            else:
                logger.error(
                    "[ERROR] [MERGE] Blob service not available, cannot upload merged file list"
                )
                raise ValueError("Blob service not available")

            # Clean up server-side worker-specific JSON files
            for worker_id in worker_stats.keys():
                try:
                    worker_file_list_path = os.path.join(
                        self.worker_file_lists_dir,
                        f"{bot_id}-filelist-worker-{worker_id}.json",
                    )
                    if os.path.exists(worker_file_list_path):
                        os.remove(worker_file_list_path)
                except Exception as cleanup_ex:
                    logger.warning(
                        f"[WARNING] [MERGE] Failed to clean up server-side worker file: {cleanup_ex}"
                    )

            # Clear the in-memory worker file lists
            with self.worker_file_lists_lock:
                self.worker_file_lists.clear()

            result = {
                "status": "success",
                "bot_id": bot_id,
                "file_list_name": f"{bot_id}-filelist.json",
                "total_workers": len(worker_stats),
                "total_files": len(final_files_list),
                "duplicates_removed": len(all_files) - len(final_files_list),
                "merged_at": timestamp,
                "worker_stats": worker_stats,
            }

            return result

        except Exception as e:
            logger.exception("[ERROR] [MERGE] Error merging worker file lists: %s", e)
            return {"status": "error", "error": str(e), "bot_id": bot_id}

    def get_worker_file_list_stats(self) -> Dict[str, Any]:
        """
        Get statistics about worker file lists without merging them.

        Returns:
            Dictionary with worker file list statistics
        """
        with self.worker_file_lists_lock:
            stats = {"total_workers": len(self.worker_file_lists), "workers": {}}

            total_files = 0
            for worker_id, worker_data in self.worker_file_lists.items():
                file_count = len(worker_data.get("files", []))
                total_files += file_count
                stats["workers"][worker_id] = {
                    "file_count": file_count,
                    "created_at": worker_data.get("created_at"),
                    "updated_at": worker_data.get("updated_at"),
                }

            stats["total_files_across_workers"] = total_files

            return stats

    def verify_all_files_in_list(self, bot_id: str = None) -> Dict[str, Any]:
        """
        Verify that all processed files are in the file list.
        Returns a summary of files in the list vs files that were processed.
        """
        try:
            if not self.blob_service:
                return {"error": "Blob service not available"}

            if not bot_id:
                config = Config()
                bot_id = config.bot_id

            file_list_name = f"{bot_id}-filelist.json"

            # Get the file list
            try:
                existing_content = self.blob_service.download_bytes(file_list_name)
                existing_data = json.loads(existing_content.decode("utf-8"))
                files_in_list = existing_data.get("files", [])

                # Get statistics from task manager
                completed_tasks = self.task_manager.get_done_tasks()
                failed_tasks = self.task_manager.get_failed_tasks()

                # Count file processing tasks
                completed_file_tasks = [
                    t for t in completed_tasks if t.work_id and t.original_filename
                ]
                failed_file_tasks = [
                    t for t in failed_tasks if t.work_id and t.original_filename
                ]

                return {
                    "files_in_list": len(files_in_list),
                    "completed_tasks": len(completed_file_tasks),
                    "failed_tasks": len(failed_file_tasks),
                    "file_list_files": [
                        f.get("name", f.get("file_name", "unknown"))
                        for f in files_in_list
                    ],
                    "completed_filenames": [
                        t.original_filename for t in completed_file_tasks
                    ],
                    "failed_filenames": [
                        t.original_filename for t in failed_file_tasks
                    ],
                    "bot_id": bot_id,
                    "file_list_name": file_list_name,
                }

            except Exception as e:
                return {"error": f"Could not read file list: {e}"}

        except Exception as e:
            return {"error": f"Verification failed: {e}"}

    def _get_content_type(self, filename: str) -> str:
        """Get content type based on file extension"""
        extension = os.path.splitext(filename)[1].lower()
        content_types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".csv": "text/csv",
            ".txt": "text/plain",
            ".json": "application/json",
        }
        return content_types.get(extension, "application/octet-stream")

    def check_service_health(self) -> Dict[str, Any]:
        """
        Check the health of the file processor and its Azure services.

        Returns:
            Dictionary containing health status and service details
        """
        services = {}
        overall_status = "healthy"

        try:
            # Check if Azure services are initialized
            if not self.azure_services_initialized:
                overall_status = "degraded"
                services["azure_services"] = {
                    "status": "unhealthy",
                    "message": "Azure services not initialized",
                    "initialized": False,
                }
            else:
                services["azure_services"] = {
                    "status": "healthy",
                    "message": "Azure services initialized",
                    "initialized": True,
                }

            # Check search service
            if self.search_service is None:
                overall_status = "degraded"
                services["search_service"] = {
                    "status": "unhealthy",
                    "message": "Azure AI Search service not available",
                }
            else:
                services["search_service"] = {
                    "status": "healthy",
                    "message": "Azure AI Search service operational",
                }

            # Check blob service
            if self.blob_service is None:
                overall_status = "degraded"
                services["blob_service"] = {
                    "status": "unhealthy",
                    "message": "Blob storage service not available",
                }
            else:
                services["blob_service"] = {
                    "status": "healthy",
                    "message": "Blob storage service operational",
                }

            # Check indexer
            if self.indexer is None:
                overall_status = "degraded"
                services["indexer"] = {
                    "status": "unhealthy",
                    "message": "Indexer not available",
                }
            else:
                services["indexer"] = {
                    "status": "healthy",
                    "message": "Indexer operational",
                }

            # Check task manager
            if self.task_manager is None:
                overall_status = "unhealthy"
                services["task_manager"] = {
                    "status": "unhealthy",
                    "message": "Task manager not available",
                }
            else:
                # Get task manager statistics
                stats = self.get_processing_statistics()
                services["task_manager"] = {
                    "status": "healthy",
                    "message": "Task manager operational",
                    "active_workers": stats.get("active_workers", 0),
                    "queued_tasks": stats.get("queued", 0),
                    "processing_tasks": stats.get("processing", 0),
                }

            return {
                "status": overall_status,
                "message": f"File processor is {overall_status}",
                "services": services,
            }

        except Exception as e:
            logger.error(f"Error checking file processor health: {e}")
            return {
                "status": "unhealthy",
                "message": f"Health check failed: {str(e)}",
                "services": services,
            }

    def _initialize_azure_services(self):
        """Initialize Azure services for file processing"""
        if self.azure_services_initialized and self.search_service is not None:
            logger.debug("[DEBUG] [AZURE SKIP] Azure services already initialized")
            return  # Already initialized

        try:
            cfg = Config()
            search_endpoint = (
                f"https://{cfg.azure_search_service_name}.search.windows.net"
            )

            logger.debug(
                f"[DEBUG] [SEARCH INIT] Initializing Azure AI Search with endpoint: {search_endpoint}"
            )
            self.search_service = AzureAISearchService()

            # Initialize Blob Storage
            # Use storage account name for Managed Identity authentication
            storage_account_name = cfg.azure_storage_account_name
            container_url = f"https://{storage_account_name}.blob.core.windows.net/{cfg.azure_storage_container_name}"

            logger.debug(
                f"[DEBUG] [BLOB INIT] Initializing Blob Storage - Account: {storage_account_name}, Container: {cfg.azure_storage_container_name}"
            )
            self.blob_service = BlobStorageService(
                account_name=cfg.azure_storage_account_name,
                container_name=cfg.azure_storage_container_name,
                container_url=container_url,
            )

            # Initialize LLM Client for embeddings using Managed Identity
            logger.debug(
                f"[DEBUG] [LLM INIT] Initializing LLM Client - Endpoint: {cfg.azure_openai_endpoint}, Deployment: {cfg.azure_openai_embedding_deployment}"
            )
            self.embedding_client = EmbeddingClient()

            # Initialize Indexer
            logger.debug("[DEBUG] [INDEXER INIT] Initializing Ingestion Indexer")
            self.indexer = IngestionIndexer(
                search=self.search_service,
                storage=self.blob_service,
                llm=self.embedding_client,  # Pass EmbeddingClient, not ._client
                container_url=container_url,
                uploader_id="background_worker",
            )

            # Mark as successfully initialized
            self.azure_services_initialized = True

        except Exception as e:
            logger.error(f"[ERROR] [AZURE ERROR] Failed to initialize Azure services: {e}")
            logger.error(f"[ERROR] [AZURE ERROR] Exception type: {type(e).__name__}")

            # Reset all services to None on failure and mark as not initialized
            self.search_service = None
            self.blob_service = None
            self.llm_client = None
            self.indexer = None
            self.azure_services_initialized = False

            raise ValueError(f"Azure services initialization failed: {e}")

    def _get_metadata_for_file(self, filename: str) -> Optional[pd.Series]:
        """
        Look up metadata for a file from the in-memory metadata DataFrame.

        Args:
            filename: Name of the file to look up

        Returns:
            pandas Series with metadata for the file, or raises ValueError if not found
        """
        # Check if metadata is loaded
        if self.metadata_df is None:
            error_msg = (
                f"No metadata loaded in memory. "
                f"When filters are enabled, you must upload a metadata file with required headers: "
                f"{Config().required_headers}. Please upload the metadata file first."
            )
            logger.error(f"[ERROR] [METADATA] {error_msg}")
            raise ValueError(error_msg)

        file_name_field = "file_name"  # Required field

        # Check for file_name field
        if file_name_field not in self.metadata_df.columns:
            logger.error(
                f"[ERROR] [METADATA] Required column '{file_name_field}' not found in metadata"
            )
            logger.debug(
                f"[DEBUG] [METADATA] Available columns: {list(self.metadata_df.columns)}"
            )
            raise ValueError(
                f"Required column '{file_name_field}' not found in metadata file"
            )

        # Find matching row (case-insensitive, handle different file extensions)

        # Try exact match first
        matching_rows = self.metadata_df[
            self.metadata_df[file_name_field].str.lower() == filename.lower()
        ]

        # If no exact match, try without extension (in case metadata has different extension)
        if matching_rows.empty:
            filename_without_ext = os.path.splitext(filename)[0].lower()
            matching_rows = self.metadata_df[
                self.metadata_df[file_name_field]
                .str.lower()
                .str.replace(r"\.[^.]*$", "", regex=True)
                == filename_without_ext
            ]
            if not matching_rows.empty:
                logger.info(
                    f"[INFO] [METADATA] Found match by filename without extension: {filename_without_ext}"
                )

        if matching_rows.empty:
            available_files = self.metadata_df[file_name_field].tolist()
            error_msg = (
                f"File '{filename}' not found in metadata. "
                f"Available files in metadata: {available_files[:10]}{'... (showing first 10)' if len(available_files) > 10 else ''}"
            )
            logger.error(f"[ERROR] [METADATA] {error_msg}")
            raise ValueError(error_msg)

        if len(matching_rows) > 1:
            logger.warning(
                f"[WARNING] [METADATA] Multiple rows found for '{filename}', using first match"
            )

        metadata_row = matching_rows.iloc[0]
        logger.debug(f"[DEBUG] [METADATA] Metadata values: {metadata_row.to_dict()}")

        return metadata_row

    def _process_file_task(
        self,
        work_id: str,
        original_filename: str,
        file_path: str,
        file_size: int,
        bot_id: str = None,
        metadata: dict = None,
    ):
        """Main file processing task function with real-time progress updates"""

        # Get task for progress updates
        task = self.task_manager.get_task_by_work_id(work_id)

        def update_progress(percentage: int, message: str = None):
            """Update progress and broadcast via WebSocket"""
            if task:
                self.task_manager.update_task_progress(task.id, percentage)
                if message:
                    self.task_manager.update_task_metadata(
                        task.id, {"current_message": message}
                    )

            # Broadcast to WebSocket clients
            if self.connection_manager:
                try:
                    import asyncio

                    # Get the event loop and broadcast the update
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        # No event loop in this thread, skip WebSocket broadcast
                        return

                    upload_record = self.get_upload_info(work_id)

                    # Schedule the coroutine in the main event loop
                    loop.create_task(
                        self.connection_manager.broadcast_to_work_id(
                            work_id,
                            {
                                "type": "status_update",
                                "work_id": work_id,
                                "data": upload_record,
                            },
                        )
                    )
                except Exception as e:
                    logger.debug(f"Failed to broadcast WebSocket update: {e}")

        # Create progress callback for the indexer
        def progress_callback(percentage: int, message: str):
            """Progress callback for indexer operations"""
            # Map indexer progress (0-100) to our progress range (40-90)
            if percentage >= 0:
                mapped_progress = 40 + int((percentage / 100) * 50)
                update_progress(mapped_progress, message)
            else:
                # Error case
                update_progress(percentage, message)

        # Initial progress update
        update_progress(10, "Starting file processing")

        try:
            # Check if this is a PDF and a Word document with the same name already exists
            # If so, skip indexing but still mark as completed
            file_extension = Path(original_filename).suffix.lower()
            base_name = original_filename.rsplit(".", 1)[0]

            if file_extension == ".pdf":
                with open(file_path, "rb") as f:
                    pdf_bytes = f.read()
                # Check if Word document with same base name exists
                word_extensions = [".docx", ".doc"]

                for word_ext in word_extensions:
                    word_filename = f"{base_name}{word_ext}"
                    if self.blob_service.blob_exists(word_filename):
                        logger.info(
                            f"[INFO] [SKIP INDEXING] PDF '{original_filename}' matches existing Word document '{word_filename}' - skipping indexing"
                        )
                        update_progress(
                            95,
                            f"Skipped indexing - Word version already indexed as {word_filename}",
                        )

                        self.blob_service.upload_bytes(
                            original_filename, pdf_bytes, content_type="application/pdf"
                        )

                        update_progress(97, "Updating file list")
                        try:
                            self._update_file_list_in_blob(
                                filename=original_filename,
                                file_size=file_size,
                                file_uri=None,
                                bot_id=bot_id,
                                csv_metadata=metadata if metadata else None,
                            )
                        except Exception as file_list_ex:
                            logger.warning(
                                f"[WARNING] [FILE LIST] Failed to update file list: {file_list_ex}"
                            )
                        update_progress(
                            100,
                            "PDF uploaded successfully (using existing Word document index)",
                        )
                        return

            # Step 1: Initialize Azure services if needed (20% progress)
            if not self.azure_services_initialized:
                update_progress(15, "Initializing Azure services")
                self._initialize_azure_services()

            update_progress(20, "Azure services ready")

            # Step 2: Initialize Model Orchestrator (30% progress) - Skip for now
            update_progress(30, "Preparing file for processing")

            # Step 3: Process the uploaded file with indexer (40-90% progress)
            update_progress(40, "Starting file content extraction")

            if self.indexer:
                # Check if metadata is available and filters are enabled
                cfg = Config()
                metadata_row = None

                # Only use metadata if filters are enabled
                if cfg.has_filters:
                    # Metadata is required when filters are enabled
                    if self.metadata_df is None:
                        error_msg = (
                            f"Filters are enabled but no metadata file has been uploaded. "
                            f"Please upload a metadata file with required headers: {cfg.required_headers}"
                        )
                        logger.error(f"[ERROR] [METADATA] {error_msg}")
                        raise ValueError(error_msg)

                    update_progress(42, "Looking up file metadata")

                    try:
                        # This will raise ValueError with clear message if metadata is missing or invalid
                        metadata_row = self._get_metadata_for_file(original_filename)
                        update_progress(45, "Metadata found - processing file")
                    except ValueError as e:
                        logger.error(
                            f"[ERROR] [METADATA] Could not find metadata for {original_filename}: {e}"
                        )
                        # For PDF files with filters enabled, metadata is required
                        if original_filename.lower().endswith(".pdf"):
                            raise
                        else:
                            logger.warning(
                                "[WARNING] [METADATA] Non-PDF file, continuing without metadata"
                            )
                            metadata_row = None
                else:
                    # Filters are disabled - process file without metadata
                    metadata_row = None

                # Use the single file processor with progress callback and metadata
                success = self.indexer.process_single_file_with_progress(
                    file_path,
                    original_filename,
                    metadata_row=metadata_row,  # Pass only CSV metadata to indexer (None if filters disabled)
                    progress_callback=progress_callback,
                    use_chapter_chunking=self.config.use_chapter_chunking,  # Enable chapter-based chunking for Word documents
                )
                if not success:
                    raise ValueError(f"File processing failed for {original_filename}")
            else:
                logger.warning(
                    f"[WARNING] [FILE PROCESS] No indexer available for work_id: {work_id}"
                )
                update_progress(90, "File processing completed (indexer not available)")

            # Step 4: File processing complete (95% progress)
            update_progress(95, "Finalizing file processing")

            # Step 4.5: Update file list in blob storage (97% progress)
            update_progress(97, "Updating file list")

            # Always attempt to update file list, even if processing failed partially
            try:
                self._update_file_list_in_blob(
                    filename=original_filename,
                    file_size=file_size,
                    file_uri=None,  # Will be auto-generated based on config
                    bot_id=bot_id,  # Use bot_id from upload headers
                    csv_metadata=metadata_row,  # Pass only CSV metadata from spreadsheet
                )
            except Exception as file_list_ex:
                logger.exception(
                    "[ERROR] [FILE LIST] Failed to update file list for %s: %s",
                    original_filename,
                    file_list_ex,
                )
                # Don't fail the entire process if file list update fails, but log it thoroughly

            # Step 5: Cleanup (100% progress)
            self._cleanup_temp_files(file_path)
            update_progress(100, "File processing completed successfully")

            return {"status": "completed", "work_id": work_id}

        except Exception as e:
            logger.exception(
                "[ERROR] [PROCESSING ERROR] Error processing file %s (work_id=%s)",
                original_filename,
                work_id,
            )
            logger.error(f"[ERROR] [PROCESSING ERROR] File path: {file_path}")
            logger.error(f"[ERROR] [PROCESSING ERROR] File size: {file_size}")
            logger.error(f"[ERROR] [PROCESSING ERROR] Bot ID: {bot_id}")

            update_progress(-1, f"Error processing file: {str(e)}")

            # Even if processing failed, try to update the file list with basic info
            try:
                self._update_file_list_in_blob(
                    filename=original_filename,
                    file_size=file_size,
                    file_uri=None,
                    bot_id=bot_id,
                    csv_metadata=None,  # No metadata since processing failed
                )
            except Exception as fallback_ex:
                logger.error(
                    f"[ERROR] [FALLBACK] Failed to update file list even in fallback mode: {fallback_ex}"
                )

            # Cleanup on error
            try:
                self._cleanup_temp_files(file_path)
            except Exception:
                logger.warning(
                    "%s task_processor.cleanup_on_error_failed file=%s",
                    BACKEND_EXCEPTION_TAG,
                    file_path,
                    exc_info=True,
                )

            raise

    def _cleanup_temp_files(self, file_path: str):
        """Clean up temporary files"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"[DEBUG] [CLEANUP] Removed temporary file: {file_path}")
        except Exception as e:
            logger.warning(
                f"[WARNING] [CLEANUP WARNING] Failed to remove temp file {file_path}: {e}"
            )

    def start_cleanup_manager(self):
        """Start the background cleanup manager thread"""
        if self.cleanup_thread is None or not self.cleanup_thread.is_alive():
            self.cleanup_running = True
            self.cleanup_thread = threading.Thread(
                target=self._cleanup_manager_loop, name="CleanupManager", daemon=True
            )
            self.cleanup_thread.start()

    def stop_cleanup_manager(self):
        """Stop the background cleanup manager thread"""
        self.cleanup_running = False
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=5)

    def _cleanup_manager_loop(self):
        """Main cleanup manager loop that runs periodically"""
        while self.cleanup_running:
            try:
                self._perform_cleanup_scan()
            except Exception as e:
                logger.error(f"[ERROR] [CLEANUP ERROR] Error during cleanup scan: {e}")

            # Sleep for the cleanup interval, but check periodically if we should stop
            for _ in range(self.cleanup_interval):
                if not self.cleanup_running:
                    break
                time.sleep(1)

    def _perform_cleanup_scan(self):
        """Perform a cleanup scan of the temp_uploads directory"""
        if not os.path.exists(self.temp_dir):
            return

        current_time = datetime.now()
        files_cleaned = 0
        files_skipped = 0

        logger.debug(f"[DEBUG] [CLEANUP SCAN] Starting cleanup scan of {self.temp_dir}")

        # Get all pending and in-progress file paths to avoid cleaning them
        protected_files = self._get_protected_file_paths()

        try:
            for filename in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, filename)

                # Skip if not a file
                if not os.path.isfile(file_path):
                    continue

                # Skip if file is protected (still being processed)
                if file_path in protected_files:
                    files_skipped += 1
                    logger.debug(
                        f"[DEBUG] [CLEANUP SKIP] Protected file (still processing): {filename}"
                    )
                    continue

                # Check file age
                try:
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    file_age = (current_time - file_mtime).total_seconds()

                    if file_age >= self.file_age_threshold:
                        # File is old enough to be cleaned up
                        os.remove(file_path)
                        files_cleaned += 1
                    else:
                        files_skipped += 1
                        logger.debug(
                            f"[DEBUG] [CLEANUP SKIP] File too new: {filename} (age: {file_age:.0f}s < {self.file_age_threshold}s)"
                        )

                except OSError as e:
                    logger.warning(
                        f"[WARNING] [CLEANUP WARNING] Cannot access file {filename}: {e}"
                    )
                    files_skipped += 1

        except OSError as e:
            logger.error(
                f"[ERROR] [CLEANUP ERROR] Cannot scan directory {self.temp_dir}: {e}"
            )
            return

        if files_cleaned > 0 or files_skipped > 0:
            logger.debug(
                f"[DEBUG] [CLEANUP COMPLETE] Scan complete: {files_cleaned} files cleaned, {files_skipped} files skipped"
            )
        else:
            logger.debug("[DEBUG] [CLEANUP COMPLETE] Scan complete: no files found to clean")

    def _get_protected_file_paths(self) -> set:
        """Get file paths that are currently being processed and should not be cleaned up"""
        protected_paths = set()

        # Get all pending and in-progress tasks
        pending_tasks = self.task_manager.get_pending_tasks()
        in_progress_tasks = self.task_manager.get_in_progress_tasks()

        # Collect file paths from tasks that are still active
        for task in pending_tasks + in_progress_tasks:
            if hasattr(task, "file_path") and task.file_path:
                protected_paths.add(task.file_path)

        return protected_paths

    def get_cleanup_statistics(self) -> Dict[str, Any]:
        """Get cleanup manager statistics"""
        try:
            temp_files = []
            if os.path.exists(self.temp_dir):
                for filename in os.listdir(self.temp_dir):
                    file_path = os.path.join(self.temp_dir, filename)
                    if os.path.isfile(file_path):
                        temp_files.append(filename)

            protected_files = self._get_protected_file_paths()

            return {
                "cleanup_running": self.cleanup_running,
                "cleanup_interval": self.cleanup_interval,
                "file_age_threshold": self.file_age_threshold,
                "temp_dir": self.temp_dir,
                "total_temp_files": len(temp_files),
                "protected_files": len(protected_files),
                "cleanable_files": len(temp_files)
                - len(
                    [
                        f
                        for f in temp_files
                        if os.path.join(self.temp_dir, f) in protected_files
                    ]
                ),
            }
        except Exception as e:
            logger.error(
                f"[ERROR] [CLEANUP STATS ERROR] Error getting cleanup statistics: {e}"
            )
            return {"cleanup_running": self.cleanup_running, "error": str(e)}
