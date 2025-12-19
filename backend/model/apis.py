"""
API Response Models for Bot in a Box Backend

This module contains Pydantic models for API responses including bot responses,
citations, images, and error responses.
"""

from typing import Optional, List
from pydantic import BaseModel
from enum import Enum


class UserRole(Enum):
    """User roles for role-based access control"""

    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super-admin"


class Citation(BaseModel):
    """Citation model for document references"""

    id: int
    title: str
    url: str
    hover_text: str
    page_number: str
    section_number: Optional[str] = None
    chapter: Optional[str] = None
    chunk_type: Optional[str] = None
    file_name: Optional[str] = None  # Added for PDF viewer
    doc_id: Optional[str] = None  # Added for document ID if available


class ImageData(BaseModel):
    """Image data model for document images"""

    citation_id: int
    page: int
    image_data_url: str


class ImageGroup(BaseModel):
    """Image group model containing multiple images from a document"""

    id: int
    title: str
    url: str
    hover_text: str
    ref_id: str
    images: List[ImageData]


class BotResponseData(BaseModel):
    """Bot response data model containing the main response content"""

    MessageID: str
    markdown: str
    images: List[ImageGroup]
    references: List[Citation]


class BotResponse(BaseModel):
    """Complete bot response model"""

    data: BotResponseData


class ErrorResponse(BaseModel):
    """Standard error response model"""

    status: int
    reason: str
    location: str
    serviceName: str = "biab-v2-backend"
    timestamp: str
    message: str
    errors: Optional[List[str]] = None


class QueryRequest(BaseModel):
    """Request model for query endpoint"""

    text: Optional[str] = None
    filters: Optional[dict] = None


class ContentFilteringResponse:
    """Response class for handling content filter errors from Azure OpenAI"""

    def __init__(self, response_text: str = ""):
        self.source_nodes = []
        self._response_text = response_text

    def __str__(self):
        return self._response_text


# --- Helper Functions ---


def create_bot_response(
    MessageID: str,
    markdown: str,
    images: List[ImageGroup] = None,
    references: List[Citation] = None,
) -> BotResponse:
    """
    Helper function to create a BotResponse object

    Args:
        message_id: Unique identifier for the question
        markdown: The response text in markdown format
        images: List of image groups (optional)
        references: List of citations (optional)

    Returns:
        BotResponse: Complete bot response object
    """
    return BotResponse(
        data=BotResponseData(
            MessageID=MessageID,
            markdown=markdown,
            images=images or [],
            references=references or [],
        )
    )


def create_error_response(
    status: int,
    reason: str,
    location: str,
    message: str,
    timestamp: str,
    errors: List[str] = None,
) -> ErrorResponse:
    """
    Helper function to create an ErrorResponse object

    Args:
        status: HTTP status code
        reason: HTTP reason phrase
        location: Request location/endpoint
        message: Error message
        timestamp: Error timestamp
        errors: List of detailed errors (optional)

    Returns:
        ErrorResponse: Standard error response object
    """
    return ErrorResponse(
        status=status,
        reason=reason,
        location=location,
        message=message,
        timestamp=timestamp,
        errors=errors,
    )
