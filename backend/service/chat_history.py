"""
Chat History Service Client for interacting with external chat history API
"""

import os
import uuid
import requests
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

# Import chat history models from centralized data_model package
from model import (
    ChatHistoryCreate,
    FeedbackUpdateRequest,
    ChatExportRequest,
    ChatHistoryQuery,
)

logger = logging.getLogger(__name__)


class ChatHistoryService:
    """Service for managing chat history with external API"""

    def __init__(self, BASE_URL: str = None):
        self.BASE_URL = BASE_URL or os.getenv("CHAT_HISTORY_API_URL")
        self.timeout = 30
        self.session = requests.Session()
        logger.debug(
            f"[DEBUG] [CHAT HISTORY SERVICE] Initialized with BASE_URL: {self.BASE_URL}"
        )

    def add_message(
        self,
        chat_data: ChatHistoryCreate,
        message_id: Optional[str] = None,
        is_public: bool = False,
    ) -> Dict[str, Any]:
        """
        Add a new chat message to the history

        This method uses a messageID provided by the frontend, or generates one
        internally if not provided, then sends the complete message data to the
        external chat history service.

        Args:
            chat_data: ChatHistoryCreate object containing message details
            message_id: Optional messageID from frontend (if None, generates new one)

        Returns:
            Dict containing:
            - success: Boolean indicating if the operation succeeded
            - data: Dict containing the message data with messageID
            - error: Error message if operation failed

        Note:
            The messageID is preferably provided by the frontend. If not provided,
            it is generated using uuid.uuid4() and included in both
            the payload sent to external service and the returned response.
        """
        try:
            # Use provided messageID from frontend, or generate one if not provided
            if message_id:
                messageID = message_id
            else:
                messageID = str(uuid.uuid4())
                logger.debug(
                    f"[DEBUG] [ADD MESSAGE] Generated messageID (no frontend ID provided): '{messageID}'"
                )

            # Convert timestamp to proper format for the external service
            if chat_data.timestamp:
                if isinstance(chat_data.timestamp, datetime):
                    # Convert datetime to UTC ISO format with Z suffix
                    if chat_data.timestamp.tzinfo is None:
                        # Assume UTC if no timezone info
                        timestamp_str = (
                            chat_data.timestamp.replace(tzinfo=timezone.utc)
                            .isoformat()
                            .replace("+00:00", "Z")
                        )
                    else:
                        # Convert to UTC and format
                        timestamp_str = (
                            chat_data.timestamp.astimezone(timezone.utc)
                            .isoformat()
                            .replace("+00:00", "Z")
                        )
                elif isinstance(chat_data.timestamp, str):
                    try:
                        # Parse string timestamp and convert to UTC ISO format
                        if chat_data.timestamp.endswith("Z"):
                            dt = datetime.fromisoformat(
                                chat_data.timestamp.replace("Z", "+00:00")
                            )
                        else:
                            dt = datetime.fromisoformat(chat_data.timestamp)
                        # Ensure UTC and add Z suffix
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        timestamp_str = (
                            dt.astimezone(timezone.utc)
                            .isoformat()
                            .replace("+00:00", "Z")
                        )
                    except ValueError as ve:
                        logger.warning(
                            f"[WARNING] [ADD MESSAGE] Timestamp parsing failed: {ve}, using current time"
                        )
                        timestamp_str = (
                            datetime.now(timezone.utc)
                            .isoformat()
                            .replace("+00:00", "Z")
                        )
                else:
                    # Fallback to current time
                    timestamp_str = (
                        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    )
            else:
                # Default to current UTC time with Z suffix
                timestamp_str = (
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                )

            # Prepare payload - convert datetime to string for JSON serialization
            # Sanitize references and images - remove None values and ensure correct structure
            sanitized_references = []
            if chat_data.citations:
                for ref in chat_data.citations:
                    if isinstance(ref, dict):
                        # Convert None values to empty strings or remove them
                        sanitized_ref = {}
                        for k, v in ref.items():
                            if v is None:
                                # Convert None to empty string for string fields
                                if k in [
                                    "title",
                                    "url",
                                    "hover_text",
                                    "page_number",
                                    "file_name",
                                    "doc_id",
                                ]:
                                    sanitized_ref[k] = ""
                                # Skip None for numeric fields
                                elif k == "id":
                                    sanitized_ref[k] = 0
                            else:
                                # Convert all values to strings to avoid type issues
                                sanitized_ref[k] = (
                                    str(v) if not isinstance(v, (dict, list)) else v
                                )

                        if sanitized_ref:  # Only add if there's content
                            sanitized_references.append(sanitized_ref)

            payload = {
                "MessageID": messageID,  # Include our generated messageID
                "BotID": chat_data.BotID,  # External service expects BotID (capital letters)
                "SessionID": chat_data.sessionID,
                "UserID": chat_data.userID,
                "query": chat_data.query,
                "response": chat_data.response,
                "timestamp": timestamp_str,
                "feedback": (
                    chat_data.feedback if chat_data.feedback is not None else 0
                ),  # Always include feedback
                "citations": sanitized_references,  # Cosmos DB expects 'citations' not 'references'
                "images": chat_data.images,  # Flat list of image URL strings
                "public": is_public,  # Mark message as public if session is shared
            }
            # Validate citations is a list of dicts
            if not isinstance(payload.get("citations"), list):
                logger.error(
                    f"[ERROR] [ADD MESSAGE] Citations must be a list, got {type(payload.get('citations'))}"
                )
                return {
                    "success": False,
                    "error": f"Invalid citations type: expected list, got {type(payload.get('citations'))}",
                }

            # Validate images is a list of strings
            if not isinstance(payload.get("images"), list):
                logger.error(
                    f"[ERROR] [ADD MESSAGE] Images must be a list, got {type(payload.get('images'))}"
                )
                return {
                    "success": False,
                    "error": f"Invalid images type: expected list, got {type(payload.get('images'))}",
                }

            # Ensure each citation is a dict (not a Pydantic model)
            for i, ref in enumerate(payload.get("citations", [])):
                if not isinstance(ref, dict):
                    logger.error(
                        f"[ERROR] [ADD MESSAGE] Citation {i} is not a dict: {type(ref)}"
                    )
                    return {
                        "success": False,
                        "error": f"Invalid citation format at index {i}: expected dict, got {type(ref)}",
                    }

            # Ensure each image is a string (URL)
            for i, img in enumerate(payload.get("images", [])):
                if not isinstance(img, str):
                    logger.error(
                        f"[ERROR] [ADD MESSAGE] Image {i} is not a string: {type(img)} - {img}"
                    )
                    return {
                        "success": False,
                        "error": f"Invalid image format at index {i}: expected string (URL), got {type(img)}",
                    }

            # Validate required fields before sending
            required_fields = [
                "MessageID",
                "BotID",
                "SessionID",
                "UserID",
                "query",
                "response",
                "timestamp",
            ]
            missing_fields = [
                field for field in required_fields if not payload.get(field)
            ]
            if missing_fields:
                logger.error(
                    f"[ERROR] [ADD MESSAGE] Missing required fields: {missing_fields}"
                )
                return {
                    "success": False,
                    "error": f"Missing required fields: {missing_fields}",
                }

            # Validate field types and constraints
            if not isinstance(payload["feedback"], int):
                logger.error(
                    f"[ERROR] [ADD MESSAGE] Invalid feedback type: {type(payload['feedback'])}"
                )
                return {
                    "success": False,
                    "error": f"Invalid feedback type, expected int, got {type(payload['feedback'])}",
                }

            url = f"{self.BASE_URL}/v1/bots/{chat_data.BotID}/users/{chat_data.userID}/sessions/{chat_data.sessionID}/messages"

            response = self.session.post(url, json=payload, timeout=self.timeout)

            if response.status_code in [200, 201]:
                result = response.json()

                # Ensure the response includes our messageID
                if isinstance(result, dict):
                    result["id"] = (
                        messageID  # Override with our generated ID (use "id" for internal response)
                    )
                else:
                    result = {
                        "id": messageID
                    }  # Create result with our ID if response is unexpected

                return {"success": True, "data": result}
            else:
                error_text = response.text
                logger.error(
                    f"[ERROR] [ADD MESSAGE] Failed with status {response.status_code}"
                )
                logger.error(f"[ERROR] [ADD MESSAGE] Error response: {error_text}")

                # Enhanced error logging for debugging 422 validation errors
                if response.status_code == 422:
                    logger.error(
                        f"[ERROR] [ADD MESSAGE] 422 VALIDATION ERROR - Payload sent: {payload}"
                    )
                    try:
                        error_detail = response.json()
                        logger.error(
                            f"[ERROR] [ADD MESSAGE] 422 Error details: {error_detail}"
                        )
                    except Exception:
                        logger.error(
                            "[ERROR] [ADD MESSAGE] 422 Error response is not valid JSON"
                        )

                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {error_text}",
                }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] [ADD MESSAGE] Connection error: {str(e)}")
            logger.error(
                f"[ERROR] [ADD MESSAGE] External service at {self.BASE_URL} appears to be unreachable"
            )
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. External service may not be running.",
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"[ERROR] [ADD MESSAGE] Timeout error: {str(e)}")
            return {"success": False, "error": f"Timeout error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [ADD MESSAGE] Request error: {str(e)}")
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [ADD MESSAGE] Unexpected error: {str(e)}")
            logger.exception("Full exception details:")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def get_user_history(self, query: ChatHistoryQuery) -> Dict[str, Any]:
        """Get chat messages per user for a time period using the new endpoint"""
        try:
            # Extract required parameters from query
            bot_id = query.BotID
            user_id = query.UserID

            if not bot_id or not user_id:
                return {"success": False, "error": "BotID and userID are required"}

            # Build the new endpoint URL
            endpoint = f"/v1/bots/{bot_id}/users/{user_id}"
            url = f"{self.BASE_URL}{endpoint}"

            # Build query parameters
            params = {}

            # Add limit and offset if specified
            if hasattr(query, "limit") and query.limit:
                params["limit"] = query.limit
            if hasattr(query, "offset") and query.offset:
                params["offset"] = query.offset

            # Add period parameter (default to 'day' if not specified)
            # You can extend this to map from query parameters if needed
            params["period"] = "day"  # Default period

            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                result = response.json()

                # The new endpoint returns the expected format directly
                return {"success": True, "data": result}
            else:
                logger.error(
                    f"[ERROR] [GET USER HISTORY] Failed with status {response.status_code}: {response.text}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}",
                }

        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [GET USER HISTORY] Connection error: {str(e)}")
            return {"success": False, "error": f"Connection error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [GET USER HISTORY] Unexpected error: {str(e)}")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def get_user_history_export(self, query: ChatExportRequest) -> Dict[str, Any]:
        """Search chat history with filtering options"""
        try:
            url = f"{self.BASE_URL}/v1/bots/{query.BotID}/users/{query.UserID}/"

            # Remove None values from the query
            query_data = {k: v for k, v in query.model_dump().items() if v is not None}
            response = self.session.get(url, params=query_data, timeout=self.timeout)

            if response.status_code == 200:
                result = response.json()
                # Get all unique session IDs and group messages by session_id based on created_at
                items = result.get("items", [])
                if items:
                    # First, get all unique session IDs
                    unique_session_ids = list(
                        set(
                            item.get("SessionID")
                            for item in items
                            if item.get("SessionID")
                        )
                    )

                    # Group all messages per session_id and sort by created_at
                    grouped_items = []
                    session_groups = {}

                    # Group messages by session ID
                    for item in items:
                        session_id = item.get("SessionID")
                        if session_id:
                            if session_id not in session_groups:
                                session_groups[session_id] = []
                            session_groups[session_id].append(item)

                    # Create list of newest messages per session for sorting
                    session_newest_messages = []
                    for session_id in unique_session_ids:
                        if session_id in session_groups:
                            # Find the newest message in this session
                            newest_message = max(
                                session_groups[session_id],
                                key=lambda x: x.get("created_at", ""),
                            )
                            session_newest_messages.append(
                                (session_id, newest_message.get("created_at", ""))
                            )

                    # Sort sessions by newest message time (newest sessions first)
                    session_newest_messages.sort(key=lambda x: x[1])

                    # Now process sessions in the sorted order
                    session_data = []
                    for session_id, _ in session_newest_messages:
                        if session_id in session_groups:
                            # Sort messages within session by created_at (newest first - chronological order like ChatGPT)
                            session_messages = sorted(
                                session_groups[session_id],
                                key=lambda x: x.get("created_at", ""),
                                reverse=True,
                            )
                            session_data.append(session_messages)

                    # session_data now contains the session messages in the correct order
                    grouped_items = session_data

                    # Replace items with grouped items
                    result["items"] = grouped_items

                return {"success": True, "data": result}
            else:
                logger.error(
                    f"[ERROR] [SEARCH HISTORY] Failed with status {response.status_code}: {response.text}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}",
                }

        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [SEARCH HISTORY] Connection error: {str(e)}")
            return {"success": False, "error": f"Connection error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [SEARCH HISTORY] Unexpected error: {str(e)}")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def update_feedback(self, feedback_data: FeedbackUpdateRequest) -> Dict[str, Any]:
        """Update feedback for a specific chat message"""
        try:
            url = f"{self.BASE_URL}/v1/bots/{feedback_data.BotID}/users/{feedback_data.UserID}/sessions/{feedback_data.SessionID}/messages/{feedback_data.id}/feedback"

            # Payload should contain all fields - external API expects MessageID not id
            payload = {
                "BotID": feedback_data.BotID,
                "MessageID": feedback_data.id,  # External API expects MessageID
                "SessionID": feedback_data.SessionID,
                "UserID": feedback_data.UserID,
                "feedback": feedback_data.feedback,
            }

            response = self.session.patch(url, json=payload, timeout=self.timeout)

            if response.status_code == 200:
                result = response.json()
                return {"success": True, "data": result}
            else:
                error_text = response.text
                logger.error(
                    f"[ERROR] [UPDATE FEEDBACK] Failed with status {response.status_code}"
                )
                logger.error(f"[ERROR] [UPDATE FEEDBACK] Error response: {error_text}")

                # Check if it's a "not found" error
                if "not found" in error_text.lower():
                    logger.error("[ERROR] [UPDATE FEEDBACK] Message not found in database!")
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {error_text}",
                }

        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [UPDATE FEEDBACK] Connection error: {str(e)}")
            return {"success": False, "error": f"Connection error: {str(e)}"}

    def get_user_session(
        self,
        query: Optional[ChatHistoryQuery] = None,
        userID: Optional[str] = None,
        sessionID: Optional[str] = None,
        bot_id: Optional[str] = None,
        UserID: Optional[str] = None,
        SessionID: Optional[str] = None,
        BotID: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get all messages for a specific session using the dedicated session messages endpoint"""
        try:
            # Support both ChatHistoryQuery object and keyword arguments
            if query:
                bot_id_val = query.BotID
                user_id_val = query.UserID
                session_id_val = query.SessionID
            else:
                # Handle keyword arguments (support both naming conventions)
                bot_id_val = bot_id or BotID
                user_id_val = userID or UserID
                session_id_val = sessionID or SessionID

            if not bot_id_val or not user_id_val or not session_id_val:
                return {
                    "success": False,
                    "error": "BotID, UserID, and SessionID are required",
                }

            # Use the specific session messages endpoint
            endpoint = f"/v1/bots/{bot_id_val}/users/{user_id_val}/sessions/{session_id_val}/messages"
            url = f"{self.BASE_URL}{endpoint}"

            # Parameters for pagination (get all messages)
            params = {
                "limit": 1000,  # Get up to 1000 messages
                "offset": 0,
            }

            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                messages = data.get("items", [])

                return {
                    "success": True,
                    "data": {
                        "messages": messages,
                        "total_count": data.get("total_count", len(messages)),
                        "has_more": data.get("has_more", False),
                        "SessionID": session_id_val,
                        "UserID": user_id_val,
                        "BotID": bot_id_val,
                    },
                }
            elif response.status_code == 404:
                logger.warning(
                    f"[WARNING] [GET SESSION MESSAGES] Session {session_id_val} not found"
                )
                return {
                    "success": False,
                    "error": f"Session {session_id_val} not found",
                }
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                logger.error(
                    f"[ERROR] [GET SESSION MESSAGES] Failed with status {response.status_code}: {response.text}"
                )
                return {"success": False, "error": error_msg}

        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [GET SESSION MESSAGES] Request error: {str(e)}")
            return {"success": False, "error": f"Connection error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [GET SESSION MESSAGES] Unexpected error: {str(e)}")
            return {
                "success": False,
                "error": f"Error retrieving session messages: {str(e)}",
            }

    def get_sessions_with_titles(
        self,
        user_id: str,
        bot_id: str,
        after_timestamp: Optional[datetime] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """
        Get sessions with generated titles for display from the chat history service.

        Args:
            user_id (str): The ID of the user to fetch sessions for
            bot_id (str): The bot ID
            after_timestamp (datetime): Optional timestamp to filter sessions created after this time
            limit (int): Maximum number of sessions to return (default: 5)

        Returns:
            Dict[str, Any]: Response containing:
                - success: Boolean indicating if the operation succeeded
                - data: Dict with session titles in the format:
                    {
                        "BotID": "bot_001",
                        "UserID": "user_67890",
                        "SessionID_title_map": {
                            "session_12345": "Title 1",
                            "session_67890": "Title 2"
                        }
                    }
                - error: Error message if operation failed
        """
        try:
            url = f"{self.BASE_URL}/v1/bots/{bot_id}/users/{user_id}/sessions/titles"

            # Add query parameters if after_timestamp is provided
            params = {}
            if after_timestamp:
                # Convert datetime to ISO format string for the query parameter
                if isinstance(after_timestamp, datetime):
                    if after_timestamp.tzinfo is None:
                        after_timestamp = after_timestamp.replace(tzinfo=timezone.utc)
                    timestamp_str = after_timestamp.isoformat()
                else:
                    timestamp_str = str(after_timestamp)
                params["after_timestamp"] = timestamp_str

            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                result = response.json()
                # The external service returns the full object with BotID, UserID, and SessionID_title_map
                return {"success": True, "data": result}
            else:
                error_text = response.text
                logger.error(
                    f"[ERROR] [GET SESSION TITLES] Failed with status {response.status_code}"
                )
                logger.error(f"[ERROR] [GET SESSION TITLES] Error response: {error_text}")
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {error_text}",
                }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] [GET SESSION TITLES] Connection error: {str(e)}")
            logger.error(
                f"[ERROR] [GET SESSION TITLES] External service at {self.BASE_URL} appears to be unreachable"
            )
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. External service may not be running.",
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"[ERROR] [GET SESSION TITLES] Timeout error: {str(e)}")
            return {"success": False, "error": f"Timeout error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [GET SESSION TITLES] Request error: {str(e)}")
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [GET SESSION TITLES] Unexpected error: {str(e)}")
            logger.exception("Full exception details:")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def make_session_public(
        self,
        session_id: str,
        user_id: str,
        bot_id: str,
        is_public: bool,
        share_token: Optional[str] = None,
        share_token_expires_at: Optional[str] = None,
        share_token_created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Make a session public or private by creating/updating session share metadata in CosmosDB.
        Stores share token and expiration information when making public, or clears it when making private.

        Args:
            session_id: Session identifier
            user_id: User identifier (session owner)
            bot_id: Bot identifier
            is_public: Whether the session is public/shared (True) or private (False)
            share_token: Optional share token string (required when is_public=True)
            share_token_expires_at: Optional ISO timestamp when token expires (required when is_public=True)
            share_token_created_at: Optional ISO timestamp when token was created (required when is_public=True)

        Returns:
            Dict containing:
                - success: Boolean indicating if the operation succeeded
                - data: Dict containing the session share metadata
                - error: Error message if operation failed
        """
        try:
            url = f"{self.BASE_URL}/v1/bots/{bot_id}/users/{user_id}/sessions/{session_id}/metadata"

            payload = {
                "SessionID": session_id,
                "BotID": bot_id,
                "UserID": user_id,
                "is_public": is_public,
                "share_token": share_token,
                "share_token_expires_at": share_token_expires_at,
                "share_token_created_at": share_token_created_at,
                "updated_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }

            response = self.session.put(url, json=payload, timeout=self.timeout)

            if response.status_code in [200, 201]:
                result = response.json()

                return {"success": True, "data": result}
            else:
                error_text = response.text
                logger.error(
                    f"[ERROR] [SESSION METADATA] Failed with status {response.status_code}: {error_text}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {error_text}",
                }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] [SESSION METADATA] Connection error: {str(e)}")
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. External service may not be running.",
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"[ERROR] [SESSION METADATA] Timeout error: {str(e)}")
            return {"success": False, "error": f"Timeout error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [SESSION METADATA] Request error: {str(e)}")
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [SESSION METADATA] Unexpected error: {str(e)}")
            logger.exception("Full exception details:")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def get_session_metadata(
        self, session_id: str, user_id: str, bot_id: str
    ) -> Dict[str, Any]:
        """
        Get session metadata document from CosmosDB.

        Args:
            session_id: Session identifier
            user_id: User identifier
            bot_id: Bot identifier

        Returns:
            Dict containing:
                - success: Boolean indicating if the operation succeeded
                - data: Dict containing the session metadata (or None if not found)
                - error: Error message if operation failed
        """
        try:
            url = f"{self.BASE_URL}/v1/bots/{bot_id}/users/{user_id}/sessions/{session_id}/metadata"

            response = self.session.get(url, timeout=self.timeout)

            if response.status_code == 200:
                result = response.json()
                return {"success": True, "data": result}
            elif response.status_code == 404:
                return {"success": True, "data": None}
            else:
                error_text = response.text
                logger.error(
                    f"[ERROR] [SESSION METADATA] Failed with status {response.status_code}: {error_text}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {error_text}",
                }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] [SESSION METADATA] Connection error: {str(e)}")
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. External service may not be running.",
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"[ERROR] [SESSION METADATA] Timeout error: {str(e)}")
            return {"success": False, "error": f"Timeout error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [SESSION METADATA] Request error: {str(e)}")
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [SESSION METADATA] Unexpected error: {str(e)}")
            logger.exception("Full exception details:")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def get_session_metadata_by_share_token(
        self, share_token: str, bot_id: str
    ) -> Dict[str, Any]:
        """
        Get session metadata by share_token (no user_id required).
        This allows querying session metadata when only the share_token is available.

        Args:
            share_token: Share token to lookup
            bot_id: Bot identifier

        Returns:
            Dict containing:
                - success: Boolean indicating if the operation succeeded
                - data: Dict containing the session metadata (or None if not found)
                - error: Error message if operation failed
        """
        try:
            url = f"{self.BASE_URL}/v1/bots/{bot_id}/share-tokens/{share_token}"

            response = self.session.get(url, timeout=self.timeout)

            if response.status_code == 200:
                result = response.json()
                return {"success": True, "data": result}
            elif response.status_code == 404:
                return {"success": True, "data": None}
            else:
                error_text = response.text
                logger.error(
                    f"[ERROR] [SESSION METADATA] Failed with status {response.status_code}: {error_text}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {error_text}",
                }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] [SESSION METADATA] Connection error: {str(e)}")
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. External service may not be running.",
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"[ERROR] [SESSION METADATA] Timeout error: {str(e)}")
            return {"success": False, "error": f"Timeout error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [SESSION METADATA] Request error: {str(e)}")
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [SESSION METADATA] Unexpected error: {str(e)}")
            logger.exception("Full exception details:")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def patch_session_make_public(
        self, session_id: str, user_id: str, bot_id: str
    ) -> Dict[str, Any]:
        """
        Mark all messages in a session as public by setting public=True for all messages.
        Uses PATCH endpoint to update the session.

        Args:
            session_id: Session identifier
            user_id: User identifier (session owner)
            bot_id: Bot identifier

        Returns:
            Dict containing:
                - success: Boolean indicating if the operation succeeded
                - data: Response data from the service
                - error: Error message if operation failed
        """
        try:
            url = f"{self.BASE_URL}/v1/bots/{bot_id}/users/{user_id}/sessions/{session_id}/public"

            # PATCH request to mark session as public
            # The endpoint requires SessionID, BotID, UserID, and public: true in the body
            payload = {
                "SessionID": session_id,
                "BotID": bot_id,
                "UserID": user_id,
                "public": True,
            }

            response = self.session.patch(url, json=payload, timeout=self.timeout)

            if response.status_code in [200, 204]:
                result = response.json() if response.content else {}
                return {"success": True, "data": result}
            else:
                error_text = response.text
                logger.error(
                    f"[ERROR] [SESSION PATCH] Failed with status {response.status_code}: {error_text}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {error_text}",
                }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] [SESSION PATCH] Connection error: {str(e)}")
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. External service may not be running.",
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"[ERROR] [SESSION PATCH] Timeout error: {str(e)}")
            return {"success": False, "error": f"Timeout error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [SESSION PATCH] Request error: {str(e)}")
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [SESSION PATCH] Unexpected error: {str(e)}")
            logger.exception("Full exception details:")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def patch_session_make_private(
        self, session_id: str, user_id: str, bot_id: str
    ) -> Dict[str, Any]:
        """
        Mark all messages in a session as private by setting public=False for all messages.
        Uses PATCH endpoint to update the session.

        Args:
            session_id: Session identifier
            user_id: User identifier (session owner)
            bot_id: Bot identifier

        Returns:
            Dict containing:
                - success: Boolean indicating if the operation succeeded
                - data: Response data from the service
                - error: Error message if operation failed
        """
        try:
            url = f"{self.BASE_URL}/v1/bots/{bot_id}/users/{user_id}/sessions/{session_id}/public"

            # PATCH request to mark session as private
            # The endpoint requires SessionID, BotID, UserID, and public: false in the body
            payload = {
                "SessionID": session_id,
                "BotID": bot_id,
                "UserID": user_id,
                "public": False,
            }

            response = self.session.patch(url, json=payload, timeout=self.timeout)

            if response.status_code in [200, 204]:
                result = response.json() if response.content else {}
                return {"success": True, "data": result}
            else:
                error_text = response.text
                logger.error(
                    f"[ERROR] [SESSION PATCH] Failed with status {response.status_code}: {error_text}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {error_text}",
                }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] [SESSION PATCH] Connection error: {str(e)}")
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. External service may not be running.",
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"[ERROR] [SESSION PATCH] Timeout error: {str(e)}")
            return {"success": False, "error": f"Timeout error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [SESSION PATCH] Request error: {str(e)}")
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [SESSION PATCH] Unexpected error: {str(e)}")
            logger.exception("Full exception details:")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def get_public_session(self, session_id: str, bot_id: str) -> Dict[str, Any]:
        """
        Get a public session by session_id.
        This endpoint fetches all messages of the session and ensures all have public=True.

        Args:
            session_id: Session identifier
            bot_id: Bot identifier

        Returns:
            Dict containing:
                - success: Boolean indicating if the operation succeeded
                - data: Dict containing session messages (all with public=True)
                - error: Error message if operation failed
        """
        try:
            url = f"{self.BASE_URL}/v1/bots/{bot_id}/sessions/{session_id}/public"

            response = self.session.get(url, timeout=self.timeout)

            if response.status_code == 200:
                result = response.json()
                # Check if items array exists and has messages (session is actually public)
                items = result.get("items", [])
                if not items or len(items) == 0:
                    # Session exists but is not public (returns 200 with empty items)
                    return {
                        "success": False,
                        "error": "Session exists but is not public",
                        "data": None,
                    }

                return {"success": True, "data": result}
            elif response.status_code == 404:
                return {"success": False, "error": "Session not found", "data": None}
            else:
                error_text = response.text
                logger.error(
                    f"[ERROR] [PUBLIC SESSION] Failed with status {response.status_code}: {error_text}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {error_text}",
                }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] [PUBLIC SESSION] Connection error: {str(e)}")
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. External service may not be running.",
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"[ERROR] [PUBLIC SESSION] Timeout error: {str(e)}")
            return {"success": False, "error": f"Timeout error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERROR] [PUBLIC SESSION] Request error: {str(e)}")
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.error(f"[ERROR] [PUBLIC SESSION] Unexpected error: {str(e)}")
            logger.exception("Full exception details:")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    def get_bot_statistics(
        self, bot_id: str, time_range: str = "today"
    ) -> Dict[str, Any]:
        """
        Get bot statistics for a specified time period

        Args:
            bot_id (str): The bot identifier for statistics retrieval
            time_range (str): Time period filter - 'today', 'this_week', or 'this_month'

        Returns:
            Dict containing:
            - success: Boolean indicating if the operation succeeded
            - data: Dict containing bot statistics with all metrics
            - error: Error message if operation failed
        """
        try:
            # 1.1 Parameter validation logic
            # Validate time_range against allowed values
            allowed_ranges = ["today", "this_week", "this_month"]
            if time_range not in allowed_ranges:
                error_msg = f"Invalid range '{time_range}'. Must be one of: {', '.join(allowed_ranges)}"
                logger.error(f"[ERROR] [GET BOT STATISTICS] {error_msg}")
                return {"success": False, "error": error_msg}

            # Validate bot_id is non-empty string
            if not bot_id or not isinstance(bot_id, str) or not bot_id.strip():
                error_msg = "bot_id must be a non-empty string"
                logger.error(f"[ERROR] [GET BOT STATISTICS] {error_msg}")
                return {"success": False, "error": error_msg}

            # 1.2 HTTP request handling
            # Construct GET request to `/v1/bots/{bot_id}/stats` endpoint
            url = f"{self.BASE_URL}/v1/bots/{bot_id}/stats"
            params = {"range": time_range}

            # Use existing session and timeout configuration
            response = self.session.get(url, params=params, timeout=self.timeout)
            # 1.3 Response processing
            if response.status_code == 200:
                # Parse successful JSON responses
                result = response.json()

                # Extract all required metrics from API response and map to internal format
                statistics_data = {
                    "BotID": bot_id,
                    "total_messages": result.get("total_messages", 0),
                    "total_active_users": result.get("total_active_users", 0),
                    "average_sessions_per_user": result.get(
                        "average_sessions_per_user", 0.0
                    ),
                    "total_sessions": result.get("total_sessions", 0),
                    "total_feedback": result.get("total_feedback", 0),
                    "positive_feedback": result.get("positive_feedback", 0),
                    "negative_feedback": result.get("negative_feedback", 0),
                }
                return {"success": True, "data": statistics_data}
            else:
                # 1.4 Comprehensive error handling
                error_text = response.text

                # Process 4xx client errors with API error details
                if 400 <= response.status_code < 500:
                    error_msg = f"HTTP {response.status_code}: {error_text}"
                    logger.error(f"[ERROR] [GET BOT STATISTICS] Client error - {error_msg}")

                    # Special handling for 404 - bot not found
                    if response.status_code == 404:
                        error_msg = f"Bot '{bot_id}' not found"

                    return {"success": False, "error": error_msg}

                # Process 5xx server errors with diagnostic information
                elif response.status_code >= 500:
                    error_msg = (
                        f"HTTP {response.status_code}: Server error - {error_text}"
                    )
                    logger.error(f"[ERROR] [GET BOT STATISTICS] Server error - {error_msg}")
                    return {"success": False, "error": error_msg}

                # Other status codes
                else:
                    error_msg = f"HTTP {response.status_code}: {error_text}"
                    logger.error(
                        f"[ERROR] [GET BOT STATISTICS] Unexpected status - {error_msg}"
                    )
                    return {"success": False, "error": error_msg}

        # 1.4 Handle connection errors with appropriate messaging
        except requests.exceptions.ConnectionError as e:
            error_msg = (
                f"Connection error: {str(e)}. External service may not be running."
            )
            logger.error(f"[ERROR] [GET BOT STATISTICS] {error_msg}")
            logger.error(
                f"[ERROR] [GET BOT STATISTICS] External service at {self.BASE_URL} appears to be unreachable"
            )
            return {"success": False, "error": error_msg}

        # Handle timeout scenarios with retry suggestions
        except requests.exceptions.Timeout as e:
            error_msg = f"Timeout error: {str(e)}. Please try again later."
            logger.error(f"[ERROR] [GET BOT STATISTICS] {error_msg}")
            return {"success": False, "error": error_msg}

        # Handle other request exceptions
        except requests.exceptions.RequestException as e:
            error_msg = f"Request error: {str(e)}"
            logger.error(f"[ERROR] [GET BOT STATISTICS] {error_msg}")
            return {"success": False, "error": error_msg}

        # Handle unexpected errors
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"[ERROR] [GET BOT STATISTICS] {error_msg}")
            logger.exception("Full exception details:")
            return {"success": False, "error": error_msg}
