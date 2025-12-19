"""
Content retrieval endpoints for query, PDF, and image retrieval.

This module contains endpoints for:
- /v1/query - Query endpoint for RAG-based responses
- /v1/get-pdf/{filename} - PDF file retrieval
- /v1/image/{image_path:path} - Image file retrieval
"""

import json
import logging
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Header, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.responses import Response as StarletteResponse
from functools import partial  # <--- Added
from concurrent.futures import ThreadPoolExecutor
import asyncio

from model import (
    BotResponse,
    Citation,
    ErrorResponse,
    ImageData,
    ImageGroup,
    QueryRequest,
    create_bot_response,
    create_chat_history_entry,
)
from service.middleware import get_current_user_from_request

logger = logging.getLogger("main")

# Constants
BAD_REQUEST = "Bad Request"
INTERNAL_SERVER_ERROR = "Internal Server Error"

# Create router
router = APIRouter()
rag_executor = ThreadPoolExecutor(max_workers=10)
# Global references to main.py objects (will be set by main.py after initialization)
orchestrator = None
config = None
chat_history_service = None
file_processor = None
session_share_service = None


def set_dependencies(orch, cfg, chat_svc, file_proc, share_svc=None):
    """
    Set dependencies from main.py to avoid circular import.
    This should be called by main.py after all services are initialized.
    """
    global orchestrator, config, chat_history_service, file_processor, session_share_service
    orchestrator = orch
    config = cfg
    chat_history_service = chat_svc
    file_processor = file_proc
    session_share_service = share_svc


# --- Helper Functions ---


def clean_text(text):
    """Strip trailing whitespace from input"""
    return text.strip()


def process_query(user_id, bot_id, session_id, text=None, file=None, filters=None):
    """
    Process a query using the RAG orchestrator.

    Note: This function requires orchestrator to be initialized in main.py
    """
    # Check if orchestrator is available
    if orchestrator is None:
        logger.error("RAGOrchestrator is not available - initialization failed")
        raise ValueError(
            "RAG system is not available. Please check system configuration."
        )

    # if file - future implementation
    if text:
        cleaned_text = clean_text(text)
        try:
            query_tokens = 0
            if orchestrator and hasattr(orchestrator, "count_tokens"):
                query_tokens = orchestrator.count_tokens(cleaned_text)
            else:
                query_tokens = len(cleaned_text.split())
            logger.info(
                "LLM_ENTRY_1 session=%s user=%s bot=%s query_chars=%d query_tokens=%d filters=%d",
                session_id,
                user_id,
                bot_id,
                len(cleaned_text),
                query_tokens,
                len(filters or {}) if filters else 0,
            )
        except Exception:
            logger.debug("LLM_ENTRY_LOG_FAIL", exc_info=True)
    else:
        logger.error("No input provided")
        raise ValueError("No input provided. Must provide text or file.")

    # Pass filters and session info to orchestrator query for memory support
    result = orchestrator.query_with_chat_engine(
        cleaned_text,
        filters=filters if filters else {},
        SessionID=session_id,
        UserID=user_id,
        BotID=bot_id,
    )
    return result


def orchestrator_to_bot_response(orchestrator_result, message_id: Optional[str] = None):
    """
    Transforms a RAGOrchestrator result into a single BotResponse object.

    Args:
        orchestrator_result: Expected dict structure:
          {
            "answer": str | Any,           # main markdown/text
            "sources": [                   # optional
              {
                "content": str,
                "score": float | None,
                "metadata": {
                  "file_name": str,
                  "page_number": int | str | None,
                  "language": str | None,
                  "access_level": str | None,
                  "images": [str] | None    # optional
                }
              },
              ...
            ],
            "num_sources_used": int,
            "method": "direct_search" | "error"
          }
        message_id: Question identifier provided by frontend (generated if not provided)
    """

    # Normalize the orchestrator result into a dict
    if orchestrator_result is None:
        raise ValueError("RAGOrchestrator returned None - internal processing error")

    # Pull answer; fallback to common alternative locations just in case
    raw_markdown = orchestrator_result.get("answer")
    # Ensure it's a string
    markdown = raw_markdown if isinstance(raw_markdown, str) else str(raw_markdown)

    sources = orchestrator_result.get("sources") or []
    if not isinstance(sources, list):
        # Make sure we can iterate
        sources = list(sources) if sources is not None else []

    # Create citations from sources
    citations = []
    image_groups = []

    for idx, source in enumerate(sources):
        citation_id = idx + 1
        metadata = source.get("metadata", {})

        # Extract file_name from source directly (not from metadata)
        file_name = source.get(
            "file_name", metadata.get("file_name", "Unknown Document")
        )
        page_number = metadata.get("page_number", "N/A")
        content = source.get("content", "")

        # Create citation
        citation = Citation(
            id=citation_id,
            title=file_name,
            url="#",  # Could be enhanced with actual document URLs if available
            hover_text=content if content else f"{file_name} - Page {page_number}",
            page_number=str(page_number) if page_number else "N/A",
            section_number=metadata.get("section_number"),
            chapter=metadata.get("chapter"),
            chunk_type=metadata.get("chunk_type"),
            file_name=file_name,  # Include file_name for PDF viewer
            doc_id=metadata.get("id"),  # Include document ID if available
        )
        citations.append(citation)

        # Create image group if images are available in metadata (but not for DOCX files)
        images_data = metadata.get("images", [])
        file_extension = file_name.lower().split(".")[-1] if "." in file_name else ""
        is_docx_file = file_extension in ["docx", "doc"]

        if images_data and isinstance(images_data, list) and not is_docx_file:
            image_list = []
            for img_idx, img_data_url in enumerate(images_data):
                image_list.append(
                    ImageData(
                        citation_id=citation_id,
                        page=(
                            int(page_number)
                            if isinstance(page_number, (int, str))
                            and str(page_number).isdigit()
                            else 1
                        ),
                        section_number=metadata.get("section_number", ""),
                        chapter=metadata.get("chapter", ""),
                        image_data_url=img_data_url,
                    )
                )

            if image_list:
                if metadata.get("section_number"):
                    hover_text = (
                        f"{file_name} - Section {metadata.get('section_number')}"
                    )
                elif metadata.get("chapter"):
                    hover_text = f"{file_name} - Chapter {metadata.get('chapter')}"
                else:
                    hover_text = f"{file_name} - Page {page_number}"
                image_groups.append(
                    ImageGroup(
                        id=citation_id,
                        title=file_name,
                        url="#",
                        hover_text=hover_text,
                        ref_id=f"doc_{citation_id}",
                        images=image_list,
                    )
                )

    # Create the complete response object using the helper function
    return create_bot_response(
        MessageID=message_id,
        markdown=markdown,
        images=image_groups,
        references=citations,
    )


# --- Endpoints ---


@router.post(
    "/v1/query",
    response_model=BotResponse,
    responses={
        200: {"model": BotResponse, "description": "Successful Response"},
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {
            "model": ErrorResponse,
            "description": "Forbidden - Authentication required",
        },
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
    summary="Submit a user query and receive a bot response (Authentication required)",
    tags=["User Query"],
)
async def user_query(
    request: Request,
    session_id: str = Header(
        ..., alias="SessionID", description="Session identifier (required)"
    ),
    message_id: Optional[str] = Header(
        None,
        alias="MessageID",
        description="Message identifier (generated by frontend)",
    ),
    text: Optional[str] = Form(None, description="Text query"),
):
    """Query endpoint for RAG-based responses with images and citations"""

    # Get current user from middleware (admin access already validated by middleware)
    current_user = get_current_user_from_request(request)
    user_id = current_user.get("user_id") if current_user else None

    location = str(request.url)
    timestamp = datetime.now(timezone.utc).isoformat()

    # BotID is now taken from config instead of headers
    bot_id = config.bot_id

    try:
        # OPTIMIZED: Read bytes directly and parse with Pydantic
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            # Read bytes directly from request body
            body_bytes = await request.body()

            # Parse directly from bytes using Pydantic (skips intermediate dict)
            try:
                query_request = QueryRequest.model_validate_json(body_bytes)
                text = query_request.text
                filters = query_request.filters or {}
            except Exception as parse_error:
                logger.warning(
                    f"Failed to parse JSON with Pydantic, falling back: {parse_error}"
                )
                # Fallback to original method
                body = await request.json()
                text = body.get("text")
                filters = body.get("filters", {})
        else:
            # Handle form data (for backward compatibility)
            form = await request.form()
            file = form.get("file") if form else None
            text = form.get("text")
            filters = {}

        if not (text or file):
            logger.error("No input provided")
            error_response = ErrorResponse(
                status=400,
                reason=BAD_REQUEST,
                location=location,
                message="No input provided. Must provide text or file.",
                timestamp=timestamp,
            )
            # OPTIMIZED: Use Pydantic's model_dump_json() directly
            return StarletteResponse(
                content=error_response.model_dump_json(),
                status_code=status.HTTP_400_BAD_REQUEST,
                media_type="application/json",
            )

        # Prepare user message for chat history
        if text:
            user_message = text
        else:
            user_message = ""

        try:
            loop = asyncio.get_running_loop()
            orch_result = await loop.run_in_executor(
                rag_executor,  # 1. Pass the executor pool first (or None for default)
                partial(  # 2. Use partial to handle keyword arguments
                    process_query,
                    user_id,
                    bot_id,
                    session_id,
                    text=text,  # kwarg
                    filters=filters,  # kwarg
                ),
            )
        except ValueError as ve:
            logger.error(f"ValueError in process_query: {ve}")
            error_response = ErrorResponse(
                status=400,
                reason=BAD_REQUEST,
                location=location,
                message=str(ve),
                timestamp=timestamp,
            )
            # OPTIMIZED: Use Pydantic's model_dump_json() directly
            return StarletteResponse(
                content=error_response.model_dump_json(),
                status_code=status.HTTP_400_BAD_REQUEST,
                media_type="application/json",
            )

        # Transform the result into a complete response object
        bot_response = orchestrator_to_bot_response(orch_result, message_id)

        # Save chat interaction to history service immediately after response creation
        if chat_history_service:
            try:
                # Extract the actual response text from the BotResponse structure
                response_text = bot_response.data.markdown

                # Extract references and images from bot_response
                references_data = (
                    [ref.model_dump() for ref in bot_response.data.references]
                    if bot_response.data.references
                    else []
                )

                # For chat history API, we need to flatten image data to simple URLs
                # The external API expects List[str], not List[ImageGroup]
                images_data_for_history = []
                if bot_response.data.images:
                    for img_group in bot_response.data.images:
                        # Extract image URLs from each ImageGroup
                        if hasattr(img_group, "images") and img_group.images:
                            for img in img_group.images:
                                if hasattr(img, "image_data_url"):
                                    images_data_for_history.append(img.image_data_url)

                # Keep the full image data for memory manager (it needs the full structure)
                images_data_full = (
                    [img.model_dump() for img in bot_response.data.images]
                    if bot_response.data.images
                    else []
                )

                # Validate required fields before creating chat history object
                if not session_id:
                    logger.error("[ERROR] Session ID is None or empty")
                    raise ValueError("Session ID is required")
                if not user_id:
                    logger.error("[ERROR] User ID is None or empty")
                    raise ValueError("User ID is required")
                if not bot_id:
                    logger.error("[ERROR] Bot ID is None or empty")
                    raise ValueError("Bot ID is required")
                if not user_message:
                    logger.error("[ERROR] User message is None or empty")
                    raise ValueError("User message is required")
                if not response_text:
                    logger.error("[ERROR] Response text is None or empty")
                    raise ValueError("Response text is required")

                # Create chat history object with correct field names (matching external service schema)
                chat_history = create_chat_history_entry(
                    bot_id=bot_id,
                    session_id=session_id,
                    user_id=user_id,
                    query=user_message,  # Use 'query' field as expected by the model
                    response=response_text,  # Extract markdown text from bot_response.data.markdown
                    citations=references_data,  # Include references
                    images=images_data_for_history,  # Include flattened image URLs (List[str])
                )

                # Check if session is currently shared/public before adding message
                is_session_public = False
                if session_share_service and bot_id:
                    try:
                        is_session_public = session_share_service.is_session_public(
                            session_id=session_id,
                            user_id=user_id,
                            bot_id=bot_id,
                        )
                        if is_session_public:
                            logger.info(
                                f"[INFO] [SHARE] Session {session_id} is public - new message will be marked as public"
                            )
                    except Exception as share_check_ex:
                        # Log error but don't fail the request - share check failure shouldn't break message addition
                        logger.warning(
                            f"[WARNING] [SHARE] Failed to check if session is public: {str(share_check_ex)}"
                        )

                # Attempt to save to chat history service
                result = chat_history_service.add_message(
                    chat_history, message_id=message_id, is_public=is_session_public
                )
                # Create the base response dictionary
                bot_response_dict = bot_response.model_dump()
                response_message_id = None

                if result["success"]:
                    # Update memory manager cache with this interaction (after saving to Cosmos)
                    # This ensures the memory cache is updated with references and images
                    try:
                        if orchestrator and hasattr(orchestrator, "memory_manager"):
                            orchestrator.memory_manager.add_interaction(
                                SessionID=session_id,
                                UserID=user_id,
                                BotID=bot_id,
                                user_message=user_message,
                                assistant_response=response_text,
                                references=references_data,
                                images=images_data_full,  # Use full image data for memory manager
                            )
                    except Exception as mem_ex:
                        logger.error(
                            f"[ERROR] [MEMORY] Failed to update memory manager: {mem_ex}"
                        )
                        logger.exception("Full memory update exception:")

                    # Extract messageID from chat history response
                    if result.get("data") and result["data"].get("id"):
                        response_message_id = result["data"]["id"]
                    else:
                        logger.error(
                            "[ERROR] [MAIN] No messageID found in chat history response!"
                        )
                        logger.error(
                            f"[ERROR] [MAIN] Chat history result structure: {result}"
                        )
                        # Use the frontend-provided messageID if backend didn't return one
                        if message_id:
                            response_message_id = message_id
                else:
                    logger.error(
                        f"[ERROR] Failed to save chat history: {result.get('error')}"
                    )
                    # Still use frontend-provided messageID even if save failed
                    if message_id:
                        response_message_id = message_id

                # Always add messageID to response if we have one
                if response_message_id:
                    bot_response_dict["MessageID"] = response_message_id

            except Exception as chat_ex:
                # Log error but don't fail the request - chat history failure shouldn't break the query
                logger.error(f"[ERROR] Exception saving chat history: {str(chat_ex)}")
                logger.exception("Full chat history save exception:")
                # Create the base response dictionary even when chat history fails
                bot_response_dict = bot_response.model_dump()
                # Use frontend-provided messageID even if exception occurred
                if message_id:
                    bot_response_dict["MessageID"] = message_id
        else:
            # Create the base response dictionary when chat history is disabled
            bot_response_dict = bot_response.model_dump()
            # Still include frontend-provided messageID even when chat history is disabled
            if message_id:
                bot_response_dict["MessageID"] = message_id

        # OPTIMIZED: Use Pydantic's model_dump_json() directly instead of model_dump() -> JSONResponse
        # This skips the intermediate dict serialization step
        response_json = json.dumps(
            bot_response_dict
        )  # Still need json.dumps for dict with MessageID
        return StarletteResponse(
            content=response_json,
            status_code=status.HTTP_200_OK,
            media_type="application/json",
        )
    except Exception as ex:
        logger.error(f"EXCEPTION in user_query: {ex}")
        logger.error(f"Exception type: {type(ex)}")
        error_response = ErrorResponse(
            status=500,
            reason=INTERNAL_SERVER_ERROR,
            location=location,
            message=str(ex),
            timestamp=timestamp,
        )
        # OPTIMIZED: Use Pydantic's model_dump_json() directly
        return StarletteResponse(
            content=error_response.model_dump_json(),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            media_type="application/json",
        )


# TODO Implement extra endpoint for downloading word files
@router.get(
    "/v1/get-pdf/{filename}",
    responses={
        200: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                "application/msword": {},
            },
            "description": "File retrieved successfully",
        },
        404: {"model": ErrorResponse, "description": "File not found"},
        403: {"model": ErrorResponse, "description": "Access denied"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
    summary="Retrieve file (PDF, Word, etc.) from blob storage",
    tags=["File Retrieval"],
)
async def get_pdf_file(filename: str, request: Request, page: int = 1):
    """
    Retrieve a file from Azure Blob Storage.
    Supports PDF files, Word documents (.docx, .doc), and other document types.

    Args:
        filename: Name of the file to retrieve
        page: Page number (optional, for frontend convenience - not used in backend)

    Returns:
        Response with file content and appropriate MIME type
    """

    # Get current user from middleware (auth check)
    _current_user = get_current_user_from_request(request)

    location = str(request.url)
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        # Check if blob service is available
        if not file_processor or not file_processor.blob_service:
            logger.error("[ERROR] [GET PDF] Blob service not available")
            logger.error(
                f"[ERROR] [GET PDF] file_processor exists: {file_processor is not None}"
            )
            if file_processor:
                logger.error(
                    f"[ERROR] [GET PDF] blob_service exists: {file_processor.blob_service is not None}"
                )
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=ErrorResponse(
                    status=503,
                    reason="Service Unavailable",
                    location=location,
                    message="Blob storage service not available",
                    timestamp=timestamp,
                ).model_dump(),
            )

        blob_service = file_processor.blob_service

        # Validate filename (basic security check)
        if ".." in filename or "/" in filename or "\\" in filename:
            logger.warning(f"[WARNING] [GET PDF] Invalid filename attempt: {filename}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=ErrorResponse(
                    status=400,
                    reason="Bad Request",
                    location=location,
                    message="Invalid filename format",
                    timestamp=timestamp,
                ).model_dump(),
            )

        # Check if file exists in blob storage
        blob_exists = blob_service.blob_exists(filename)

        if not blob_exists:
            # Try to find blobs where the requested filename is a substring
            logger.warning(
                "[WARNING] [GET PDF] File not found with exact name, searching with pattern matching..."
            )

            try:
                blob_list = blob_service.list_blobs()
                all_blobs = [blob.name for blob in blob_list]
                logger.info(
                    f"[INFO] [GET PDF] Total blobs in container: {len(all_blobs)}"
                )

                # Get the requested file extension to match only same type
                requested_extension = Path(filename).suffix.lower()
                filename_lower = filename.lower()

                logger.info(
                    f"[INFO] [GET PDF] Searching for files with extension '{requested_extension}' containing: '{filename_lower}'"
                )

                # Find all blobs that match the same file type
                matching_blobs = []

                for blob_name in all_blobs:
                    blob_lower = blob_name.lower()

                    # Only check files with the same extension as requested
                    if not blob_lower.endswith(requested_extension):
                        continue

                    if filename_lower in blob_lower:
                        matching_blobs.append(blob_name)

                if matching_blobs:
                    # Use the first match
                    filename = matching_blobs[0]
                else:
                    logger.error(
                        f"[ERROR] [GET PDF] No matching blobs found for: '{filename}'"
                    )
                    # Show sample document blobs for debugging
                    supported_extensions = [".pdf", ".docx", ".doc"]
                    document_blobs = [
                        b
                        for b in all_blobs
                        if any(b.lower().endswith(ext) for ext in supported_extensions)
                    ][:10]
                    logger.info(
                        f"[INFO] [GET PDF] Sample of available document blobs: {document_blobs}"
                    )

                    return JSONResponse(
                        status_code=status.HTTP_404_NOT_FOUND,
                        content=ErrorResponse(
                            status=404,
                            reason="Not Found",
                            location=location,
                            message=f"Document '{filename}' is no longer available. The file may have been removed or the search index needs to be updated. Please contact support if this issue persists.",
                            timestamp=timestamp,
                        ).model_dump(),
                    )
            except Exception as list_error:
                logger.exception(
                    "[ERROR] [GET PDF] Error listing blobs for %s: %s",
                    filename,
                    list_error,
                )
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content=ErrorResponse(
                        status=404,
                        reason="Not Found",
                        location=location,
                        message=f"File '{filename}' not found in storage",
                        timestamp=timestamp,
                    ).model_dump(),
                )  # Download the file from blob storage        # Download the file from blob storage        # Download the file from blob storage
        logger.info(f"[INFO] [GET PDF] Streaming from blob storage: {filename}")
        try:
            blob_client = blob_service.get_blob_client(filename)
            downloader = blob_client.download_blob()
        except Exception as stream_error:
            logger.exception(
                "[ERROR] [GET PDF] Unable to open blob stream %s", filename
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=ErrorResponse(
                    status=500,
                    reason="Internal Server Error",
                    location=location,
                    message=f"Failed to initiate blob download: {stream_error}",
                    timestamp=timestamp,
                ).model_dump(),
            )

        chunk_size = (
            2 * 1024 * 1024
        )  # 2MB chunks keep memory flat while maintaining throughput

        def stream_blob():
            for chunk in downloader.chunks(chunk_size):
                if chunk:
                    yield chunk

        file_size = None
        try:
            properties = downloader.properties
            if properties and getattr(properties, "size", None):
                file_size = properties.size
        except Exception:
            # Properties call can fail for some blob tiers; ignore and continue streaming
            file_size = None

        # Determine MIME type and Content-Disposition based on file extension
        file_extension = Path(filename).suffix.lower()

        # Define MIME types for supported file formats
        mime_types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
        }

        media_type = mime_types.get(file_extension, "application/pdf")  # Default to PDF

        # Determine if file should be inline (PDF) or attachment (Word docs)
        is_word_doc = file_extension in [".docx", ".doc"]
        disposition_type = "attachment" if is_word_doc else "inline"

        if file_size:
            logger.info(
                f"[INFO] [GET PDF] Prepared streaming response: {filename} (size={file_size} bytes, {media_type})"
            )
        else:
            logger.info(
                f"[INFO] [GET PDF] Prepared streaming response: {filename} (size unknown, {media_type})"
            )

        # Remove UUID prefix from filename for user-friendly download name
        def remove_uuid_prefix(filename):
            """Remove UUID prefix from filename if present"""

            # Pattern to match UUID followed by underscore at the start of filename
            # UUID format: 8-4-4-4-12 hexadecimal characters
            uuid_pattern = (
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_"
            )
            return re.sub(uuid_pattern, "", filename, flags=re.IGNORECASE)

        # Get clean filename without UUID for download
        clean_filename = remove_uuid_prefix(filename)

        # Encode filename for Content-Disposition header to handle special characters
        from urllib.parse import quote

        try:
            # Try to encode as ASCII first
            clean_filename.encode("ascii")
            disposition = f'{disposition_type}; filename="{clean_filename}"'
        except UnicodeEncodeError:
            # If filename contains non-ASCII chars, use dual encoding for max compatibility
            ascii_filename = clean_filename.encode("ascii", "ignore").decode("ascii")
            if not ascii_filename:
                # Use appropriate default based on file type
                default_name = "document" + (
                    file_extension if file_extension else ".pdf"
                )
                ascii_filename = default_name
            encoded_filename = quote(clean_filename.encode("utf-8"))
            disposition = f"{disposition_type}; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"

        # Return file with appropriate headers
        headers = {
            "Content-Disposition": disposition,
            "Cache-Control": "public, max-age=3600",
        }
        if file_size:
            headers["Content-Length"] = str(file_size)

        return StreamingResponse(stream_blob(), media_type=media_type, headers=headers)

    except Exception as e:
        logger.exception("[ERROR] [GET PDF] Error retrieving PDF %s", filename)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                status=500,
                reason="Internal Server Error",
                location=location,
                message=f"Error retrieving file: {str(e)}",
                timestamp=timestamp,
            ).model_dump(),
        )


@router.get(
    "/v1/image/{image_path:path}",
    responses={
        200: {
            "content": {
                "image/png": {},
                "image/jpeg": {},
                "image/jpg": {},
                "image/gif": {},
                "image/webp": {},
            },
            "description": "Image retrieved successfully",
        },
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {
            "model": ErrorResponse,
            "description": "Forbidden - Authentication required",
        },
        404: {"model": ErrorResponse, "description": "Image not found"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
    summary="Retrieve image from blob storage (Authentication required)",
    tags=["Image Retrieval"],
)
async def get_image(image_path: str, request: Request):
    """
    Retrieve an image file from Azure Blob Storage.

    This endpoint coordinates with the query endpoint by accepting image paths/URLs
    that are returned in the query response's image_data_url field.

    Args:
        image_path: Path or blob name of the image to retrieve.
                   Can be a simple blob name (e.g., "report_name/section_1_image_0.png")
                   or extracted from a full URL from query response.

    Returns:
        Response with image content and appropriate content type
    """

    # NOTE: No auth required - this is a public endpoint marked in middleware
    # Images are returned in query responses, so frontend needs to retrieve them without auth

    location = str(request.url)
    timestamp = datetime.now(timezone.utc).isoformat()

    # Decode the image path - convert : back to / (frontend encodes / as : to avoid APIM routing issues)
    decoded_image_path = image_path.replace("~", "/")

    try:
        # Check if blob service is available
        if not file_processor or not file_processor.blob_service:
            logger.error("[ERROR] [GET IMAGE] Blob service not available")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=ErrorResponse(
                    status=503,
                    reason="Service Unavailable",
                    location=location,
                    message="Blob storage service not available",
                    timestamp=timestamp,
                ).model_dump(),
            )

        blob_service = file_processor.blob_service

        # Extract blob name from path/URL if needed
        # Handle both simple blob names and full URLs that might come from query endpoint
        blob_name = decoded_image_path

        # If it's a full URL, extract just the blob name
        # Format might be: "https://.../container/image_path" or just "container/image_path"
        if "/" in blob_name and len(blob_name.split("/")) > 1:
            # Remove leading container URL if present (coordinate with query endpoint)
            parts = blob_name.split("/")
            # Find the blob name part (after container name if present)
            # Images are typically stored as: {report_dir}/section_{num}_image_{idx}.{ext}
            # or could be: container/{report_dir}/...
            if blob_service.container_name in parts:
                # Remove everything up to and including container name
                container_idx = parts.index(blob_service.container_name)
                blob_name = "/".join(parts[container_idx + 1 :])
            else:
                # Assume it's already a blob path
                blob_name = "/".join(parts)

        # Validate blob name (basic security check)
        if ".." in blob_name:
            logger.warning(
                f"[WARNING] [GET IMAGE] Invalid blob name attempt: {blob_name}"
            )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=ErrorResponse(
                    status=400,
                    reason="Bad Request",
                    location=location,
                    message="Invalid image path format",
                    timestamp=timestamp,
                ).model_dump(),
            )

        # Check if image exists in blob storage
        blob_exists = blob_service.blob_exists(blob_name)

        if not blob_exists:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=ErrorResponse(
                    status=404,
                    reason="Not Found",
                    location=location,
                    message=f"Image '{blob_name}' not found in storage",
                    timestamp=timestamp,
                ).model_dump(),
            )

        try:
            blob_client = blob_service.get_blob_client(blob_name)
            downloader = blob_client.download_blob()
        except Exception as stream_error:
            logger.exception(
                "[ERROR] [GET IMAGE] Unable to open blob stream %s", blob_name
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=ErrorResponse(
                    status=500,
                    reason="Internal Server Error",
                    location=location,
                    message=f"Failed to initiate blob download: {stream_error}",
                    timestamp=timestamp,
                ).model_dump(),
            )

        chunk_size = 512 * 1024  # 512KB chunks are plenty for images

        def stream_blob():
            for chunk in downloader.chunks(chunk_size):
                if chunk:
                    yield chunk

        image_size = None
        try:
            props = downloader.properties
            if props and getattr(props, "size", None):
                image_size = props.size
        except Exception:
            image_size = None

        # Determine content type from file extension
        path_obj = Path(blob_name)
        extension = path_obj.suffix.lower()

        # Map common image extensions to MIME types
        mime_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".svg": "image/svg+xml",
        }

        content_type = mime_type_map.get(extension, "image/png")

        # Fallback to mimetypes if extension not in map
        if content_type == "image/png" and extension not in mime_type_map:
            guessed_type, _ = mimetypes.guess_type(blob_name)
            if guessed_type and guessed_type.startswith("image/"):
                content_type = guessed_type

        # Get filename for Content-Disposition header
        filename = path_obj.name

        # Return image as response
        headers = {
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "public, max-age=3600",
        }
        if image_size:
            headers["Content-Length"] = str(image_size)

        logger.info(
            f"[INFO] [GET IMAGE] Streaming image: {blob_name} (size={image_size if image_size else 'unknown'})"
        )

        return StreamingResponse(
            stream_blob(), media_type=content_type, headers=headers
        )

    except Exception as e:
        logger.exception("[ERROR] [GET IMAGE] Error retrieving image %s", image_path)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                status=500,
                reason="Internal Server Error",
                location=location,
                message=f"Error retrieving image: {str(e)}",
                timestamp=timestamp,
            ).model_dump(),
        )
