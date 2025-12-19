# indexer.py
import os
import uuid
import time
import json
import logging
from typing import List, Dict, Any
import pandas as pd
from io import StringIO
from datetime import datetime
from filelock import FileLock

from io import BytesIO

from config import Config
from model import SearchDocument
from .llm_client import LLMClient
from .azure_ai_search import AzureAISearchService
from .blob_storage import BlobStorageService
from .file_processor import PDFProcessor, WordProcessor

logger = logging.getLogger(__name__)

try:
    from .utils import iso_utc_now
except ImportError:
    # Fallback if utils doesn't exist
    from datetime import datetime

    def iso_utc_now():
        return datetime.utcnow().isoformat() + "Z"


class IngestionIndexer:
    def __init__(
        self,
        *,
        search: AzureAISearchService,
        storage: BlobStorageService,
        llm: LLMClient,
        container_url: str,
        uploader_id: str,
    ):
        self.search = search
        self.storage = storage
        self.llm = llm
        self.container_url = container_url.rstrip("/")
        self.pdf = PDFProcessor()
        self.word = WordProcessor()
        self.uploader_id = (uploader_id or "system").lower()

        # Load configuration for metadata handling
        self.config = Config()
        self.file_name_field = "file_name"  # Default field for file names
        # Progress tracking
        self.progress_file = f"./progress_{self.search.index_name}.json"

    # --- CSV/Excel Metadata ---
    def _read_metadata_file(self, content: bytes, filename: str) -> pd.DataFrame:
        """Read metadata from CSV or Excel file"""
        # Check file extension
        file_ext = filename.lower().split(".")[-1] if "." in filename else ""

        if file_ext in ["xlsx", "xls"]:
            # Read Excel file
            try:
                return pd.read_excel(BytesIO(content), engine="openpyxl")
            except ImportError:
                raise ValueError(
                    "openpyxl is required to read Excel files. Please install it: pip install openpyxl"
                )
            except Exception as e:
                raise ValueError(f"Could not read Excel file: {str(e)}")
        else:
            # Read CSV file (default)
            # Try common encodings in order of likelihood
            for encoding in ["utf-8", "utf-8-sig", "latin1", "iso-8859-1", "cp1252"]:
                try:
                    return pd.read_csv(StringIO(content.decode(encoding)))
                except UnicodeDecodeError:
                    continue
            raise ValueError("Could not read CSV with common encodings")

    def _create_base_metadata(
        self,
        chunk: str,
        page_num: int,
        pdf_name: str,
        emb: List[float],
        page_data: Dict = None,
        version_id: str = None,
    ) -> Dict[str, Any]:
        """Create base metadata structure that's common across all processing functions"""
        now = iso_utc_now()
        page_data = page_data or {}

        tables_data = page_data.get("tables", [])
        tables_serialized = []
        if tables_data and isinstance(tables_data, list):
            for table in tables_data:
                if isinstance(table, dict):
                    # Serialize dict to JSON string
                    tables_serialized.append(json.dumps(table))
                elif isinstance(table, str):
                    # Already a string
                    tables_serialized.append(table)

        # Create document using the SearchDocument model
        # Convert table dictionaries to JSON strings if they exist
        tables = page_data.get("tables", [])
        if tables and isinstance(tables[0], dict):
            # Convert dict tables to JSON strings
            tables = [json.dumps(table) for table in tables]

        doc = SearchDocument(
            id=uuid.uuid4().hex,
            text=self.pdf.clean_text(chunk),
            vector=emb.tolist(),
            images=page_data.get("images", []),
            charts=page_data.get("charts", []),
            tables=tables,
            page_number=int(page_num),
            created_at=now,
            updated_at=now,
            file_name=self.pdf.clean_text(pdf_name),
            file_uri=f"{self.container_url}/{self.storage.container_name}/{pdf_name}",
            language="en",
            uploaded_by=self.uploader_id,
            access_level="public",
            version_id=version_id or uuid.uuid4().hex,
        )

        # Convert to dict for further processing
        doc_dict = doc.model_dump()

        # Add chapter-based metadata if present in page_data
        if "section_number" in page_data:
            doc_dict["section_number"] = page_data["section_number"]
        if "chapter" in page_data:
            doc_dict["chapter"] = page_data["chapter"]
        if "chunk_type" in page_data:
            doc_dict["chunk_type"] = page_data["chunk_type"]

        return doc_dict

    def _add_csv_metadata(
        self, base_doc: Dict[str, Any], row: pd.Series
    ) -> Dict[str, Any]:
        """Add CSV-based metadata to base document using filters configuration"""

        # If filters are enabled, add filter fields to the document
        if self.config.has_filters:
            if row is None:
                logger.error(
                    "[ERROR] [_add_csv_metadata] ERROR: row is None but has_filters is True!"
                )
                return base_doc

            for filter_name, filter_field in self.config.filters.items():
                # Skip if filter_field is None or empty
                if not filter_field:
                    logger.warning(
                        f"[WARNING] [_add_csv_metadata] Skipping filter '{filter_name}' - field name is None or empty"
                    )
                    continue

                # Skip file_name as it's a pointer/identifier, not metadata
                if filter_field.lower() == "file_name":
                    continue

                if filter_field in row:
                    try:
                        value = self.pdf.clean_text(str(row[filter_field]))
                        base_doc[filter_field] = value
                    except (ValueError, TypeError) as e:
                        logger.warning(
                            f"[WARNING] [_add_csv_metadata] Could not process {filter_field} from CSV: {e}"
                        )
                        base_doc[filter_field] = ""
                else:
                    logger.warning(
                        f"[WARNING] [_add_csv_metadata] Filter field '{filter_field}' not found in CSV row"
                    )
                    # Set default values for missing filter fields
                    base_doc[filter_field] = ""
        else:
            logger.info(
                "[INFO] [_add_csv_metadata] Filters disabled - skipping CSV metadata"
            )

        return base_doc

    # --- Public ops ---
    def create_or_update_index(self):
        return self.search.create_or_update_index()

    # --- Progress Tracking ---
    def _load_progress(self) -> Dict[str, Any]:
        """Load processing progress from file"""
        lock_path = self.progress_file + ".lock"
        try:
            with FileLock(lock_path, timeout=5):
                if os.path.exists(self.progress_file):
                    with open(self.progress_file, "r") as f:
                        return json.load(f)
        except Exception as e:
            logger.error(f"Error loading progress file: {str(e)}")

        return {
            "processed_files": [],
            "failed_files": [],
            "total_files": 0,
            "start_time": None,
            "last_update": None,
        }

    def _save_progress(self, progress_data: Dict[str, Any]):
        """Save processing progress to file"""
        lock_path = self.progress_file + ".lock"
        try:
            with FileLock(lock_path, timeout=5):
                progress_data["last_update"] = datetime.utcnow().isoformat()
                with open(self.progress_file, "w") as f:
                    json.dump(progress_data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving progress: {str(e)}")

    def _clear_progress(self):
        """Clear progress file"""
        lock_path = self.progress_file + ".lock"
        try:
            with FileLock(lock_path, timeout=5):
                if os.path.exists(self.progress_file):
                    os.remove(self.progress_file)
        except Exception as e:
            logger.error(f"Error clearing progress file: {str(e)}")

    def get_processing_status(self) -> Dict[str, Any]:
        """Get current processing status"""
        progress = self._load_progress()
        return {
            "processed": len(progress["processed_files"]),
            "failed": len(progress["failed_files"]),
            "total": progress["total_files"],
            "processed_files": progress["processed_files"],
            "failed_files": progress["failed_files"],
            "can_resume": progress["total_files"] > 0
            and len(progress["processed_files"]) < progress["total_files"],
            "start_time": progress["start_time"],
            "last_update": progress["last_update"],
        }

    def process_word_document_with_chapters(
        self,
        file_path: str,
        filename: str,
        metadata_row: pd.Series = None,
        progress_callback=None,
    ):
        """
        Process a Word document using chapter-based chunking for better structured content handling.
        This method is specifically designed for documents with clear chapter/section structure.

        Args:
            file_path: Local path to the Word file
            filename: Name to use for the file in the index
            metadata_row: Optional pandas Series containing metadata from CSV
            progress_callback: Optional callback function that receives (progress_percentage, message)

        Returns:
            bool: True if processing succeeded
        """
        return self.process_single_file_with_progress(
            file_path=file_path,
            filename=filename,
            metadata_row=metadata_row,
            progress_callback=progress_callback,
            use_chapter_chunking=self.config.use_chapter_chunking,
        )

    def process_single_file_with_progress(
        self,
        file_path: str,
        filename: str,
        metadata_row: pd.Series = None,
        progress_callback=None,
        use_chapter_chunking: bool = False,
    ):
        """
        Process a single PDF or Word file with progress callbacks

        Args:
            file_path: Local path to the PDF or Word file
            filename: Name to use for the file in the index
            metadata_row: Optional pandas Series containing metadata from CSV. Required when has_filters is True.
            progress_callback: Optional callback function that receives (progress_percentage, message)
            use_chapter_chunking: If True, use chapter-based chunking for Word documents (default: False)
        """
        try:
            # Determine file type
            file_extension = os.path.splitext(filename)[1].lower()
            is_word_doc = file_extension in [".docx", ".doc"]
            file_type = "Word document" if is_word_doc else "PDF"
            processor = self.word if is_word_doc else self.pdf

            # Check if file already exists in index and delete old chunks
            if progress_callback:
                try:
                    progress_callback(3, f"Checking for existing file: {filename}")
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")

            delete_result = self.search.delete_file_documents(filename)

            if delete_result.get("success"):
                deleted_count = delete_result.get("deleted_count", 0)
                if deleted_count > 0:
                    if progress_callback:
                        try:
                            progress_callback(
                                5, f"Deleted {deleted_count} old chunks for: {filename}"
                            )
                        except Exception as e:
                            logger.error(f"Error in progress callback: {e}")
                else:
                    logger.info(
                        f"[INFO] [INDEXER] No existing chunks found for file: {filename}"
                    )
            else:
                logger.warning(
                    f"[WARNING] [INDEXER] Could not check for existing chunks: {delete_result.get('message')}"
                )

            if progress_callback:
                try:
                    progress_callback(5, f"Starting processing of {filename}")
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")

            # Read the file
            if progress_callback:
                try:
                    progress_callback(10, f"Reading {file_type}: {filename}")
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")

            with open(file_path, "rb") as f:
                file_bytes = f.read()

            # Upload the actual PDF/Word file to blob storage with UUID prefix
            if progress_callback:
                try:
                    progress_callback(
                        15, f"Uploading {file_type} to storage: {filename}"
                    )
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")

            # Generate version_id for this upload (shared by all chunks from this file)
            version_id = uuid.uuid4().hex
            try:
                # Use exact filename for blob storage
                self.storage.upload_bytes(filename, file_bytes)
                logger.info(f"[INFO] [INDEXER] Uploaded {filename} to blob storage")
            except Exception as upload_ex:
                logger.error(
                    f"[ERROR] [INDEXER] Failed to upload {file_type} to blob storage: {upload_ex}"
                )
                raise ValueError(
                    f"Failed to upload {file_type} to blob storage: {upload_ex}"
                )

            # Process the file based on type
            if progress_callback:
                try:
                    progress_callback(20, f"Extracting content from: {filename}")
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")

            report_dir = os.path.splitext(os.path.basename(filename))[0].replace(
                " ", "_"
            )

            if is_word_doc:
                if use_chapter_chunking:
                    # Use chapter-based chunking for structured documents

                    # Try markdown extraction first, fall back to direct DOCX parsing
                    try:
                        chapters = self.word.extract_chapters_from_markdown(file_bytes)
                    except Exception as md_error:
                        logger.warning(
                            f"[WARNING] [INDEXER] Markdown extraction failed: {md_error}. Falling back to direct DOCX parsing."
                        )
                        chapters = self.word.extract_chapters_from_docx(file_bytes)

                    # Generate chunks based on chapter structure
                    chunks_data = self.word.chapter_based_chunking(chapters)

                    # Convert to content_by_section format for compatibility
                    # Preserve chapter and chunk_type metadata
                    content_by_section = {}
                    for idx, chunk_info in enumerate(chunks_data):
                        content_by_section[chunk_info["section_number"]] = {
                            "text": chunk_info["content"],
                            "images": [],  # Chapter-based chunking doesn't extract images yet
                            "charts": [],
                            "tables": [],
                            "section_number": chunk_info[
                                "section_number"
                            ],  # Preserve section number
                            "chapter": chunk_info[
                                "chapter"
                            ],  # Preserve chapter metadata
                            "chunk_type": chunk_info[
                                "chunk_type"
                            ],  # Preserve chunk type
                        }
                    image_batches = []
                else:
                    # Use traditional section-based extraction
                    content_by_section, image_batches = self.word.iter_word_document(
                        file_bytes, report_dir
                    )
            else:
                content_by_section, image_batches = self.pdf.iter_pdf(
                    file_bytes, report_dir
                )
            # Upload images to blob storage
            if image_batches:
                if progress_callback:
                    try:
                        progress_callback(40, f"Uploading images for: {filename}")
                    except Exception as e:
                        logger.error(f"Error in progress callback: {e}")
                self.storage.upload_batch(image_batches)

            # Create search documents
            if progress_callback:
                try:
                    progress_callback(60, f"Creating search documents for: {filename}")
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")

            docs: List[Dict[str, Any]] = []
            total_sections = len(content_by_section)

            for idx, (section_num, section) in enumerate(content_by_section.items()):
                # Update progress for each section/page
                section_progress = 60 + int((idx / total_sections) * 30)  # 60% to 90%
                section_label = "section" if is_word_doc else "page"
                if progress_callback:
                    try:
                        progress_callback(
                            section_progress,
                            f"Processing {section_label} {section_num} of {filename}",
                        )
                    except Exception as e:
                        logger.error(f"Error in progress callback: {e}")

                # Get text content - Word docs have text as list, PDFs as string
                if isinstance(section.get("text"), list):
                    text_content = "\n".join(section["text"])
                else:
                    text_content = section.get("text", "")

                # For chapter-based chunking, content is already chunked
                if use_chapter_chunking and is_word_doc:
                    chunks = [text_content]  # Already chunked, use as-is
                else:
                    chunks = processor.chunk_text(text_content, words_per_chunk=250)

                # TODO: Check if we can use batching for embeddings - asyncio.gather()
                for chunk_idx, chunk in enumerate(chunks):
                    if not chunk.strip():
                        continue

                    # Generate embedding with retry
                    try:
                        emb = self.llm.embed(chunk)
                        if chunk_idx == 0:  # Log first chunk of each section
                            logger.info(
                                f"[INFO] [INDEXER] {section_label.capitalize()} {section_num} chunk {chunk_idx}: Embedding generated successfully"
                            )
                    except Exception as e:
                        logger.warning(
                            f"[WARNING] [INDEXER] {section_label.capitalize()} {section_num} chunk {chunk_idx}: Embedding failed: {str(e)}"
                        )
                        if "429" in str(e):
                            time.sleep(3)
                            emb = self.llm.embed(chunk)
                        else:
                            logger.error(
                                f"[ERROR] [INDEXER] {section_label.capitalize()} {section_num} chunk {chunk_idx}: Skipping due to embedding error"
                            )
                            continue

                    # Create base metadata and add CSV metadata
                    # For Word docs with chapter chunking, use sequential index instead of section_num for page_number
                    page_num_value = (
                        idx + 1
                        if (use_chapter_chunking and is_word_doc)
                        else section_num
                    )
                    base_doc = self._create_base_metadata(
                        chunk, page_num_value, filename, emb, section, version_id
                    )

                    complete_doc = self._add_csv_metadata(base_doc, metadata_row)

                    docs.append(complete_doc)

            # Upload documents to search index

            if docs:
                if progress_callback:
                    try:
                        progress_callback(
                            90, f"Uploading documents to search index for: {filename}"
                        )
                    except Exception as e:
                        logger.error(f"Error in progress callback: {e}")

                self.search.upload_documents(docs)

            else:
                logger.error(
                    "[ERROR] [INDEXER] No documents were created! Check PDF processing logs above."
                )

            if progress_callback:
                try:
                    progress_callback(100, f"Successfully processed: {filename}")
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")

            logger.info(f"Successfully processed file: {filename}")
            return True

        except Exception as e:
            error_msg = f"Error processing file {filename}: {str(e)}"
            logger.error(error_msg)
            if progress_callback:
                try:
                    progress_callback(-1, error_msg)
                except Exception as cb_e:
                    logger.error(f"Error in progress callback: {cb_e}")
            raise
