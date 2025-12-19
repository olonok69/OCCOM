"""
Chat History and Session Models for Bot in a Box Backend

This module contains Pydantic models for chat history management, session handling,
feedback updates, and chat data export.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel


class ChatHistoryCreate(BaseModel):
    """
    Model for creating a new chat history entry

    This matches the external service schema for creating new chat messages.
    All fields are required except feedback, timestamp, references, and images.

    Fields:
        BotID: Identifier for the bot (e.g., "document-assistant")
        sessionID: Unique session identifier
        userID: User identifier
        query: The user's input/question
        response: The bot's response
        feedback: User feedback (-1, 0, 1) - defaults to 0 (neutral)
        timestamp: When the message was created - auto-generated if None
        citations: List of citation/reference objects from the response
        images: List of image URLs (strings) from the response
    """

    BotID: str
    sessionID: str
    userID: str
    query: str
    response: str
    feedback: Optional[int] = 0  # Default to 0 (neutral) instead of None
    timestamp: Optional[datetime] = (
        None  # Can be datetime object, will be converted to ISO format
    )
    citations: Optional[List[Dict[str, Any]]] = None  # Citations/references
    images: Optional[List[str]] = None  # Image URLs (flattened from ImageGroup objects)


class ChatHistoryResponse(BaseModel):
    """
    Model for chat history response from external service

    This represents the structure returned by the external service
    when retrieving chat history messages.

    Fields:
        id: Unique message identifier from external service
        BotID: Bot identifier
        sessionID: Session identifier
        userID: User identifier
        query: Original user query
        response: Bot response
        feedback: User feedback value (if any)
        timestamp: Message timestamp
        message_created: When the message was created in the external service
        references: List of citation/reference objects from the response
        images: List of image group objects from the response
    """

    MessageID: str
    BotID: str
    SessionID: str
    UserID: str
    query: str
    response: str
    feedback: Optional[int] = None
    created_at: datetime
    citations: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[Dict[str, Any]]] = None


class ChatHistoryQuery(BaseModel):
    """
    Model for querying chat history with filtering options

    Used to search and filter chat history from the external service.
    Only BotID is required, all other fields are optional filters.

    Fields:
        BotID: Bot identifier (required)
        sessionID: Filter by specific session (optional)
        userID: Filter by specific user (optional)
        feedback: Filter by feedback value (optional)
        start_date: Filter messages after this date (optional)
        end_date: Filter messages before this date (optional)
        limit: Maximum number of results (default: 100)
        offset: Number of results to skip (default: 0)
        last_n_questions: Get only the last N questions (optional)
    """

    BotID: str
    SessionID: Optional[str] = None
    UserID: Optional[str] = None
    feedback: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: int = 100
    offset: int = 0
    last_n_questions: Optional[int] = None


class FeedbackUpdateRequest(BaseModel):
    """
    Model for updating feedback on an existing chat message

    Used to update the feedback value for a specific message in the external service.
    UserID is optional as it's extracted from the auth token by the backend.

    Fields:
        id: Unique identifier of the message to update
        SessionID: Session containing the message
        BotID: Bot that created the message
        UserID: User who owns the message (optional, extracted from auth token)
        feedback: New feedback value (-1: thumbs down, 0: neutral, 1: thumbs up)
    """

    id: str
    SessionID: str
    BotID: str
    UserID: Optional[str] = None  # Optional since extracted from auth token
    feedback: int


class SessionCreateRequest(BaseModel):
    """Request model for creating a new chat session"""

    userID: str
    botID: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SessionResponse(BaseModel):
    """Response model for session information"""

    sessionID: str
    userID: str
    bot_id: str
    created_at: str
    last_activity: str
    metadata: Dict[str, Any]


class SessionListResponse(BaseModel):
    """Response model for listing user sessions"""

    sessions: List[SessionResponse]
    total_count: int


class ChatHistoryApiResponse(BaseModel):
    """Response model for chat history API operations"""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class ChatExportRequest(BaseModel):
    """Request model for exporting chat history"""

    UserID: str
    BotID: str
    period: str  # day, week, month, 3month, 6month, all


class ChatExportResponse(BaseModel):
    """Response model for chat history export"""

    items: List[ChatHistoryResponse]
    total_count: int
    limit: int
    offset: int
    has_more: bool


class SessionShareRequest(BaseModel):
    """Request model for creating a shareable session link"""

    expires_in_days: Optional[int] = 30  # Default 30 days


class SessionShareResponse(BaseModel):
    """Response model for share token creation"""

    success: bool
    share_token: str  # Unique token for sharing (internal use only)
    expires_at: str  # ISO timestamp when share expires
    created_at: str
    message: str


class SessionShareInfoResponse(BaseModel):
    """Response model for getting share info"""

    success: bool
    is_shared: bool  # Whether session is currently shared
    share_token: Optional[str] = None  # Internal use only
    expires_at: Optional[str] = None
    created_at: Optional[str] = None
    message: str


# --- Helper Functions ---


def create_chat_history_entry(
    bot_id: str,
    session_id: str,
    user_id: str,
    query: str,
    response: str,
    feedback: int = 0,
    citations: Optional[List[Dict[str, Any]]] = None,
    images: Optional[List[str]] = None,
) -> ChatHistoryCreate:
    """
    Helper function to create a ChatHistoryCreate object

    Args:
        bot_id: Bot identifier
        session_id: Session identifier
        user_id: User identifier
        query: User's question/input
        response: Bot's response
        feedback: User feedback value (default: 0)
        citations: List of citation/reference objects (optional)
        images: List of image URLs (strings) from ImageGroup objects (optional)

    Returns:
        ChatHistoryCreate: Chat history creation object
    """
    return ChatHistoryCreate(
        BotID=bot_id,
        sessionID=session_id,
        userID=user_id,
        query=query,
        response=response,
        feedback=feedback,
        citations=citations,
        images=images,
    )
