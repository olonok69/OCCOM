"""
Model Package for Bot in a Box Backend

This package provides all Pydantic models used throughout the application.
Models are organized into separate modules by their functional area:

- api_responses: Bot responses, citations, images, errors
- file_models: File upload, processing status, metadata
- health_models: Health checks, cleanup operations
- chat_models: Chat history, sessions, feedback

All models are re-exported from this package for backward compatibility
with existing imports.
"""

# API Response Models
from .apis import (
    Citation,
    ImageData,
    ImageGroup,
    BotResponseData,
    BotResponse,
    ErrorResponse,
    QueryRequest,
    ContentFilteringResponse,
    create_bot_response,
    create_error_response,
)

# File Management Models
from .file_models import (
    UploadResponse,
    StatusResponse,
    FileMetadata,
    FileListResponse,
    SearchDocument,
)

# Health and System Models
from .health_models import HealthResponse

# Chat History and Session Models
from .chat_models import (
    ChatHistoryCreate,
    ChatHistoryResponse,
    ChatHistoryQuery,
    FeedbackUpdateRequest,
    SessionCreateRequest,
    SessionResponse,
    SessionListResponse,
    ChatHistoryApiResponse,
    ChatExportRequest,
    ChatExportResponse,
    SessionShareRequest,
    SessionShareResponse,
    SessionShareInfoResponse,
    create_chat_history_entry,
)

# Make all models available at package level for backward compatibility
__all__ = [
    # API Response Models
    "Citation",
    "ImageData",
    "ImageGroup",
    "BotResponseData",
    "BotResponse",
    "ErrorResponse",
    "QueryRequest",
    "ContentFilteringResponse",
    "create_bot_response",
    "create_error_response",
    # File Management Models
    "UploadResponse",
    "StatusResponse",
    "FileMetadata",
    "FileListResponse",
    "SearchDocument",
    # Health and System Models
    "HealthResponse",
    # Chat History and Session Models
    "ChatHistoryCreate",
    "ChatHistoryResponse",
    "ChatHistoryQuery",
    "FeedbackUpdateRequest",
    "SessionCreateRequest",
    "SessionResponse",
    "SessionListResponse",
    "ChatHistoryApiResponse",
    "ChatExportRequest",
    "ChatExportResponse",
    "SessionShareRequest",
    "SessionShareResponse",
    "SessionShareInfoResponse",
    "create_chat_history_entry",
]
