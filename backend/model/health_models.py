"""
Health and System Models for Bot in a Box Backend

This module contains Pydantic models for health checks and system status monitoring.
"""

from typing import Dict, Any
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health check response model"""

    status: str
    timestamp: str
    services: Dict[str, Any]  # Allow flexible service data structure
    version: str = "1.0.0"
