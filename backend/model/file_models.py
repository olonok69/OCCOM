"""
File Management Models for Bot in a Box Backend

This module contains Pydantic models for file upload, processing status,
metadata, and file listing operations.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """Response model for successful file uploads"""

    work_id: str
    message: str
    filename: str
    file_size: int


class StatusResponse(BaseModel):
    """Response model for file processing status"""

    work_id: str
    status: str
    progress_percentage: int
    original_filename: str
    created_at: str
    updated_at: str
    error_message: Optional[str] = None
    completed_at: Optional[str] = None


class FileMetadata(BaseModel):
    """Model for file metadata returned from Azure AI Search"""

    name: str
    filename: Optional[str] = None
    file_name: Optional[str] = None  # Actual field from Azure Search
    file_uri: Optional[str] = None  # Actual field from Azure Search
    size: Optional[int] = None
    content_type: Optional[str] = None
    created_at: Optional[str] = None
    last_modified: Optional[str] = None
    id: Optional[str] = None
    chunk_count: Optional[int] = 1
    language: Optional[str] = None
    access_level: Optional[str] = None
    publisher: Optional[str] = None
    category: Optional[str] = None


class FileListResponse(BaseModel):
    """Response model for listing files from Azure AI Search with pagination"""

    success: bool
    files: List[FileMetadata]
    total_count: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool
    timestamp: str


class SearchDocument(BaseModel):
    """
    Model for search index document structure.
    Represents a single document chunk that will be uploaded to Azure AI Search.
    This is the base structure used by the indexer for creating searchable documents.
    """

    id: str = Field(description="Unique identifier for the document chunk")
    text: str = Field(description="Cleaned text content of the chunk")
    vector: List[float] = Field(description="Embedding vector for the text")
    images: List[str] = Field(
        default_factory=list, description="List of image URLs from the page"
    )
    charts: List[str] = Field(
        default_factory=list, description="List of chart URLs from the page"
    )
    tables: List[str] = Field(
        default_factory=list, description="List of table URLs from the page"
    )
    page_number: int = Field(description="Page number in the original document")
    created_at: str = Field(description="ISO UTC timestamp when document was created")
    updated_at: str = Field(
        description="ISO UTC timestamp when document was last updated"
    )
    file_name: str = Field(description="Name of the source file")
    file_uri: str = Field(description="Full URI to the file in blob storage")
    language: str = Field(default="en", description="Language code of the document")
    uploaded_by: str = Field(description="User ID who uploaded the document")
    access_level: str = Field(default="public", description="Access control level")
    version_id: str = Field(description="Version identifier for document updates")
