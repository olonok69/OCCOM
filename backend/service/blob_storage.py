# services/storage.py
from typing import Iterable, Tuple, Optional
import logging
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.identity import DefaultAzureCredential
import json
import os

from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class BlobStorageService:
    def __init__(self, *, account_name: str, container_name: str, container_url: str):
        # Use Managed Identity authentication
        credential = DefaultAzureCredential()
        account_url = f"https://{account_name}.blob.core.windows.net"
        self._svc = BlobServiceClient(account_url=account_url, credential=credential)
        self._container = self._svc.get_container_client(container_name)
        self.container_name = container_name
        self.container_url = container_url

    def list_blobs(self):
        return list(self._container.list_blobs())

    def upload_bytes(
        self,
        blob_name: str,
        data: bytes,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        """
        Upload bytes to blob storage with optional content type and metadata.

        Args:
            blob_name: Name of the blob to create/update
            data: Bytes data to upload
            content_type: MIME type of the file (e.g., 'application/pdf', 'text/csv', 'image/png')
            metadata: Additional custom metadata as key-value pairs

        Example:
            service.upload_bytes(
                blob_name="document.pdf",
                data=file_bytes,
                content_type="application/pdf",
                metadata={"uploaded_by": "user123", "category": "report"}
            )
        """
        # Set content settings if content_type is provided
        content_settings = None
        if content_type:
            content_settings = ContentSettings(content_type=content_type)

        # Upload with metadata and content settings
        self._container.upload_blob(
            blob_name,
            data,
            overwrite=True,
            content_settings=content_settings,
            metadata=metadata,
        )

        if content_type:
            logger.debug(
                f"Uploaded blob '{blob_name}' with content type '{content_type}'"
            )
        if metadata:
            logger.debug(
                f"Uploaded blob '{blob_name}' with metadata: {list(metadata.keys())}"
            )

    def download_bytes(self, blob_name: str) -> bytes:
        return self._container.get_blob_client(blob_name).download_blob().readall()

    def upload_batch(
        self, batches: Iterable[Tuple[str, bytes, Optional[str], Optional[dict]]]
    ):
        """
        Upload multiple blobs with optional content types and metadata.

        Args:
            batches: Iterable of tuples containing:
                - blob_name (str): Name of the blob
                - data (bytes): Bytes data to upload
                - content_type (Optional[str]): MIME type of the file
                - metadata (Optional[dict]): Additional custom metadata

        Example:
            batches = [
                ("doc1.pdf", pdf_bytes, "application/pdf", {"category": "report"}),
                ("image1.png", img_bytes, "image/png", {"uploaded_by": "user123"}),
                ("data.csv", csv_bytes, "text/csv", None)
            ]
            service.upload_batch(batches)

        Note: For backward compatibility, also supports tuples of (blob_name, data)
        """
        for batch_item in batches:
            if len(batch_item) == 2:
                # Backward compatibility: (blob_name, data)
                blob_name, data = batch_item
                self.upload_bytes(blob_name, data)
            elif len(batch_item) == 3:
                # (blob_name, data, content_type)
                blob_name, data, content_type = batch_item
                self.upload_bytes(blob_name, data, content_type=content_type)
            elif len(batch_item) == 4:
                # (blob_name, data, content_type, metadata)
                blob_name, data, content_type, metadata = batch_item
                self.upload_bytes(
                    blob_name, data, content_type=content_type, metadata=metadata
                )
            else:
                logger.warning(f"Invalid batch item format: {len(batch_item)} elements")

    def delete_blob(self, blob_name: str) -> bool:
        """Delete a specific blob"""
        try:
            self._container.delete_blob(blob_name)
            return True
        except Exception as e:
            logger.error(f"Error deleting blob {blob_name}: {str(e)}")
            return False

    def delete_all_blobs(self):
        all_blobs = self.list_blobs()
        deleted_count = 0

        for blob_name in all_blobs:
            try:
                self.delete_blob(blob_name)
                deleted_count += 1
                logger.debug(f"[DEBUG] [FACTORY RESET] Deleted blob: {blob_name}")
            except Exception as blob_ex:
                logger.error(
                    f"[ERROR] [FACTORY RESET] Failed to delete blob {blob_name}: {blob_ex}"
                )
        return deleted_count

    def blob_exists(self, blob_name: str) -> bool:
        """Check if a blob exists"""
        try:
            blob_client = self._container.get_blob_client(blob_name)
            return blob_client.exists()
        except Exception:
            return False

    def get_blob_client(self, blob_name: str):
        """Expose blob client for advanced streaming operations"""
        return self._container.get_blob_client(blob_name)

    def add_file_to_list(
        self, file_name: str, bot_id: str, file_metadata: dict = None
    ) -> dict:
        """
        Add a file to the file list JSON in blob storage, appending to existing entries.

        Args:
            file_name: Name of the file to add
            bot_id: Bot ID for the file list
            file_metadata: Optional metadata about the file (size, upload_date, etc.)

        Returns:
            Dict with success status and details
        """
        import json
        from datetime import datetime, timezone

        try:
            file_list_name = f"{bot_id}-filelist.json"

            # Download existing file list or create new one
            try:
                existing_content = self.download_bytes(file_list_name)
                existing_data = json.loads(existing_content.decode("utf-8"))
            except Exception as download_ex:
                if "BlobNotFound" in str(download_ex) or "404" in str(download_ex):
                    existing_data = {"files": []}
                else:
                    raise download_ex

            files_list = existing_data.get("files", [])

            # Check if file already exists in the list
            file_already_exists = any(
                f.get("name") == file_name or f.get("file_name") == file_name
                for f in files_list
            )

            if not file_already_exists:
                # Create file entry
                timestamp = datetime.now(timezone.utc).isoformat()
                file_entry = {
                    "name": file_name,
                    "file_name": file_name,
                    "added_at": timestamp,
                    **(file_metadata or {}),
                }

                # Append to the list
                files_list.append(file_entry)

                # Update the file list data
                updated_data = {
                    **existing_data,
                    "updated_at": timestamp,
                    "updated_by": "file_upload",
                    "total_files": len(files_list),
                    "files": files_list,
                }

                # Convert to JSON and upload
                json_content = json.dumps(updated_data, indent=2).encode("utf-8")
                self.upload_bytes(
                    file_list_name, json_content, content_type="application/json"
                )

                return {
                    "success": True,
                    "file_name": file_name,
                    "total_files": len(files_list),
                    "message": f"File added to list: {file_name}",
                }
            else:
                return {
                    "success": True,
                    "file_name": file_name,
                    "total_files": len(files_list),
                    "message": f"File already in list: {file_name}",
                    "already_existed": True,
                }

        except Exception as e:
            logger.error(f"[ERROR] Error adding file to list: {e}")
            return {
                "success": False,
                "file_name": file_name,
                "error": str(e),
                "message": f"Failed to add file to list: {str(e)}",
            }

    def delete_file_and_update_list(self, file_name: str, bot_id: str) -> dict:
        """
        Delete a file blob and remove it from the file list JSON.
        Uses exact filename matching for deletion.

        Args:
            file_name: Name of the file to delete (exact match)
            bot_id: Bot ID for the file list

        Returns:
            Dict with success status and details
        """

        try:
            deleted_blobs = []
            errors = []

            # Prepare base name for related blobs (images/charts/tables)
            base_name = file_name.rsplit(".", 1)[0]  # Remove extension
            base_name_sanitized = base_name.replace(" ", "_")

            # Get all blobs
            all_blobs = self.list_blobs()

            logger.info(
                f"[INFO] [DELETE] Searching for exact filename match: {file_name}"
            )
            logger.info(
                f"[INFO] [DELETE] Also searching for related blobs with base: {base_name_sanitized}"
            )

            # Delete blobs that match this file
            for blob in all_blobs:
                blob_name = blob.name
                should_delete = False

                # Pattern 1: Exact filename match for main file
                if blob_name == file_name:
                    should_delete = True
                    logger.info(f"[INFO] [DELETE] Found exact match: {blob_name}")

                # Pattern 2: Related blobs (images/charts/tables) with sanitized base name
                elif base_name_sanitized in blob_name and (
                    "_section_" in blob_name
                    or "_page_" in blob_name
                    or "_image_" in blob_name
                    or "_chart_" in blob_name
                    or "_table_" in blob_name
                ):
                    should_delete = True
                    logger.info(f"[INFO] [DELETE] Found related blob: {blob_name}")

                # Perform deletion
                if should_delete:
                    try:
                        self.delete_blob(blob_name)
                        deleted_blobs.append(blob_name)
                        logger.info(f"[INFO] [DELETE] Deleted blob: {blob_name}")
                    except Exception as e:
                        errors.append(f"Failed to delete blob {blob_name}: {str(e)}")
                        logger.error(f"[ERROR] Error deleting blob {blob_name}: {e}")

            # Update file list JSON
            file_list_name = f"{bot_id}-filelist.json"
            try:
                # Download existing file list
                try:
                    existing_content = self.download_bytes(file_list_name)
                    existing_data = json.loads(existing_content.decode("utf-8"))
                except Exception as download_ex:
                    if "BlobNotFound" in str(download_ex) or "404" in str(download_ex):
                        existing_data = {"files": []}
                    else:
                        raise download_ex

                # Remove file from the list
                files_list = existing_data.get("files", [])
                original_count = len(files_list)

                # Filter out the file to remove
                files_list = [
                    f
                    for f in files_list
                    if f.get("name") != file_name and f.get("file_name") != file_name
                ]

                removed_from_list = len(files_list) < original_count

                if removed_from_list:
                    # Update the file list data
                    timestamp = datetime.now(timezone.utc).isoformat()
                    updated_data = {
                        **existing_data,
                        "updated_at": timestamp,
                        "updated_by": "file_deletion",
                        "total_files": len(files_list),
                        "files": files_list,
                    }

                    # Convert to JSON and upload
                    json_content = json.dumps(updated_data, indent=2).encode("utf-8")
                    self.upload_bytes(file_list_name, json_content)

                else:
                    logger.info(f"[INFO] File not found in list: {file_name}")

            except Exception as list_ex:
                errors.append(f"Failed to update file list: {str(list_ex)}")
                logger.error(f"[ERROR] Error updating file list: {list_ex}")

            # Determine overall success
            success = len(deleted_blobs) > 0 and len(errors) == 0

            result = {
                "success": success,
                "deleted_blobs": deleted_blobs,
                "deleted_blob_count": len(deleted_blobs),
                "removed_from_list": (
                    removed_from_list if "removed_from_list" in locals() else False
                ),
                "errors": errors if errors else None,
                "message": f"Deleted {len(deleted_blobs)} blob(s) for file: {file_name}",
            }

            if errors:
                result["message"] += f" with {len(errors)} error(s)"

            return result

        except Exception as e:
            logger.error(f"[ERROR] Error in delete_file_and_update_list: {e}")
            return {
                "success": False,
                "deleted_blobs": deleted_blobs if "deleted_blobs" in locals() else [],
                "deleted_blob_count": (
                    len(deleted_blobs) if "deleted_blobs" in locals() else 0
                ),
                "removed_from_list": False,
                "errors": [str(e)],
                "message": f"Failed to delete file: {str(e)}",
            }

    def update_default_config(self):
        # 3. Reset config.json file
        logger.warning(
            "[WARNING] [FACTORY RESET] Step 3: Resetting config.json to defaults..."
        )
        try:
            config_file_path = "config.json"
            default_config_path = "default-config.json"

            # Check if default-config.json exists
            if os.path.exists(default_config_path):
                # Copy default-config.json to config.json
                import shutil

                shutil.copy2(default_config_path, config_file_path)
                logger.warning(
                    f"[WARNING] [FACTORY RESET] Copied {default_config_path} to {config_file_path}"
                )
            else:
                # Fallback: create a basic default config if default-config.json doesn't exist
                logger.warning(
                    f"[WARNING] [FACTORY RESET] {default_config_path} not found, creating basic default config"
                )
                default_config = {
                    "has_filters": False,
                    "filters": {},
                    "required_headers": [],
                    "filter_mapping": {},
                    "look_and_feel": {
                        "bot_name": "Document Chatbot",
                        "version": "1.0.0",
                        "language": "en",
                        "about_text": "AI-powered document assistant",
                        "disclaimer_text": "AI can make mistakes, please check and validate the answers.",
                        "primary_color": "#30ff00",
                        "secondary_background_color": "#cecece",
                        "background_color": "#FFFFFF",
                        "text_color": "#000000",
                        "welcome_message": "Hi! How can I assist you today?",
                    },
                    "feedback_contact_name": "",
                    "feedback_contact_email": "",
                    "faq": [],
                }

                # Write default config to file
                with open(config_file_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=2)
        except Exception as config_ex:
            logger.error(
                f"[ERROR] [FACTORY RESET] Config reset error: {config_ex}"
            )  # Determine overall success


def get_bot_config_from_blob(
    account_name: str, container_name: str, blob_name: str = "bot_config.json"
) -> dict:
    """
    Fetch bot configuration from Azure Blob Storage.

    Args:
        account_name: Azure Storage account name
        container_name: Container name where bot_config.json is stored
        blob_name: Name of the config blob (default: "bot_config.json")

    Returns:
        Dictionary containing bot configuration, or empty dict if not found

    Example:
        config = get_bot_config_from_blob("mystorageaccount", "mycontainer")
    """
    import json

    try:
        # Use Managed Identity authentication
        credential = DefaultAzureCredential()
        account_url = f"https://{account_name}.blob.core.windows.net"
        blob_service_client = BlobServiceClient(
            account_url=account_url, credential=credential
        )
        container_client = blob_service_client.get_container_client(container_name)

        # Download the blob
        blob_client = container_client.get_blob_client(blob_name)

        if not blob_client.exists():
            logger.warning(f"{blob_name} not found in container '{container_name}'")
            return {}

        # Download and parse JSON
        blob_data = blob_client.download_blob().readall()
        raw_content = blob_data.decode("utf-8")

        # Log the content for debugging (first 500 chars)
        logger.debug(f"Raw blob content (first 500 chars): {raw_content[:500]}")

        config = json.loads(raw_content)

        return config

    except json.JSONDecodeError as e:
        logger.error(f"[ERROR] Invalid JSON in {blob_name}: {e}")
        logger.error(
            f"[ERROR] JSON content around error: {raw_content[max(0, e.pos - 50) : e.pos + 50]}"
        )

        # Try to fix common JSON issues (Python booleans, etc.)
        logger.warning("[WARNING] Attempting to fix invalid JSON...")
        try:
            # Fix Python booleans (True/False) to JSON booleans (true/false)
            fixed_content = raw_content.replace(": True,", ": true,").replace(
                ": False,", ": false,"
            )
            fixed_content = fixed_content.replace(": True\n", ": true\n").replace(
                ": False\n", ": false\n"
            )
            fixed_content = fixed_content.replace(": True}", ": true}").replace(
                ": False}", ": false}"
            )
            fixed_content = (
                fixed_content.replace(": None,", ": null,")
                .replace(": None\n", ": null\n")
                .replace(": None}", ": null}")
            )

            config = json.loads(fixed_content)

            # Upload the fixed version back to blob storage
            try:
                fixed_json_bytes = json.dumps(config, indent=2).encode("utf-8")
                blob_client.upload_blob(fixed_json_bytes, overwrite=True)
            except Exception as upload_ex:
                logger.warning(f"[WARNING] Could not upload fixed JSON: {upload_ex}")

            return config

        except Exception as fix_ex:
            logger.error(f"[ERROR] Could not fix invalid JSON: {fix_ex}")
            logger.error(f"[ERROR] Full content: {raw_content}")
            return {}
    except Exception as e:
        logger.error(f"Error fetching bot config from blob storage: {str(e)}")
        return {}
