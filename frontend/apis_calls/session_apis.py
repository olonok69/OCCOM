import logging
from typing import Dict, Any, Optional

import requests
import streamlit as st  # type: ignore

try:
    from frontend.settings import settings
except Exception:
    from settings import settings


logger = logging.getLogger(__name__)


def add_message_to_session(
    user_id: str,
    session_id: str,
    query: str,
    response: str,
    message_id: str = None,
    bot_id: str = None,
    feedback: int = None,
    citations: list = None,
    images: list = None,
) -> Dict[str, Any]:
    """
    Add a new message to a session and update the persistent storage.

    Args:
        user_id (str): The ID of the user
        session_id (str): The session ID to add the message to
        query (str): The user's query/message
        response (str): The assistant's response
        message_id (str): Optional message ID (if not provided, generates a new one)
        bot_id (str): Optional bot ID (defaults to "EBRD_Bot_001")
        feedback (int): Optional feedback (1 for positive, 0 for negative, None for no feedback)
        citations (list): Optional list of citations/references for the response

    Returns:
        Dict[str, Any]: The new message object
    """
    import datetime

    new_message = {
        "BotID": bot_id,
        "created_at": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "id": message_id,
        "query": query,
        "response": response,
        "SessionID": session_id,
        "UserID": user_id,  # Keep this as UserID for local storage compatibility
    }
    if feedback is not None:
        new_message["feedback"] = feedback
    if citations is not None:
        new_message["citations"] = citations
    if images is not None:
        new_message["images"] = images
    return new_message


def get_session_titles(
    after_timestamp: Optional[str] = None, limit: int = 1000
) -> Dict[str, Any]:
    """
    Get session titles for a user from the backend API.

    Args:
        after_timestamp (str): Optional ISO timestamp to filter sessions created after this time
        limit (int): Maximum number of sessions to return (default: 1000)

    Note:
        - user_id is automatically extracted from the JWT token in st.session_state["id_token"]
        - The token is sent in the request headers, and the backend extracts user_id from it
        - No need to pass user_id as a parameter - it's handled automatically via authentication

    Returns:
        Dict[str, Any]: Response containing session titles map
            Example: {
                "BotID": "bot_001",
                "UserID": "user_67890",
                "SessionID_title_map": {
                    "session_12345": "Title 1",
                    "session_67890": "Title 2"
                }
            }
    """
    try:
        headers = settings.build_headers(None, None)
        # Build the URL
        url = f"{settings.backend_base_url}/v1/sessions/titles"

        # Provide default after_timestamp if none provided (30 days ago)
        if after_timestamp is None:
            from datetime import datetime, timezone, timedelta

            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            after_timestamp = thirty_days_ago.isoformat()

        # Add query parameters
        params = {"after_timestamp": after_timestamp, "limit": limit}

        response = requests.get(url, headers=headers, params=params, timeout=10)

        if response.status_code == 200:
            result = response.json()
            session_title_map = result.get("SessionID_title_map", {})

            if "session_titles" not in st.session_state:
                st.session_state["session_titles"] = {}

            st.session_state["session_titles"] = {
                "session_titles": session_title_map,
                "bot_id": result.get("BotID", settings.bot_id),
            }

            return {
                "success": True,
                "session_titles": session_title_map,
                "bot_id": result.get("BotID", settings.bot_id),
            }
        else:
            error_message = f"Error fetching session titles: {response.status_code} - {response.text}"
            logger.error(error_message)
            return {
                "success": False,
                "error": error_message,
                "session_titles": {},
            }

    except requests.exceptions.Timeout as e:
        error_message = f"Request timeout fetching session titles: {str(e)}"
        logger.error(error_message)
        return {
            "success": False,
            "error": error_message,
            "session_titles": {},
        }
    except requests.exceptions.RequestException as e:
        error_message = f"Request error fetching session titles: {str(e)}"
        logger.error(error_message)
        return {
            "success": False,
            "error": error_message,
            "session_titles": {},
        }
    except Exception as e:
        error_message = f"Unexpected error fetching session titles: {str(e)}"
        logger.exception(error_message)
        return {
            "success": False,
            "error": error_message,
            "session_titles": {},
        }


def update_message_feedback(
    user_id: str, session_id: str, message_id: str, feedback: int
) -> Dict[str, Any]:
    """
    Update feedback for a specific message through backend API.

    Args:
        user_id (str): The user ID
        session_id (str): The session ID
        message_id (str): The message ID
        feedback (int): Feedback value (1 for positive, 0 for negative)

    Returns:
        Dict[str, Any]: Response from the backend API
    """
    try:
        headers = settings.build_headers(session_id, message_id)

        url = f"{settings.backend_base_url}/v1/chat/feedback"

        # UserID is extracted from auth token in backend, no need to pass it
        payload = {
            "id": message_id,
            "SessionID": session_id,
            "BotID": settings.bot_id,
            "feedback": feedback,
        }

        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 200:
            result = response.json()
            return {
                "success": result.get("success", False),
                "message": result.get("message", ""),
                "data": result.get("data"),
            }
        else:
            return {
                "success": False,
                "message": f"Backend API error: {response.status_code} - {response.text}",
                "data": None,
            }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error updating feedback: {str(e)}",
            "data": None,
        }


def export_chat_history(
    user_id: str,
    period: Optional[str] = None,
    export_format: str = "json",
) -> Dict[str, Any]:
    """
    Export chat history from the backend API.

    Args:
        user_id (str): The ID of the user
        bot_id (str): The ID of the bot
        session_id (str): Optional session ID to export specific session
        start_date (str): Optional start date in ISO format
        end_date (str): Optional end date in ISO format
        format (str): Export format - "json" or "csv" (default: "json")

    Returns:
        Dict[str, Any]: Export response containing the data
            Example: {
                "success": True,
                "message": "Exported 10 messages",
                "data": [...] or "csv_string"
            }
    """
    try:
        header = settings.build_headers(None, None)
        # Build the export request payload
        payload = {
            "BotID": settings.bot_id,
            "UserID": user_id,
            "format": export_format,
            "period": period,
        }
        # Make the POST request to export endpoint
        response = requests.post(
            f"{settings.backend_base_url}/v1/chat/export",
            json=payload,
            headers=header,
            timeout=60,  # Longer timeout for exports
        )

        if response.status_code == 200:
            # Check content type to determine if it's a file download or JSON
            content_type = response.headers.get("content-type", "")

            if "application/json" in content_type:
                # JSON response
                result = response.json()
                items = result.get("items", [])
                total_count = result.get("total_count", 0)

                # Check if there's no chat history
                if total_count == 0 or not items:
                    return {
                        "success": True,
                        "message": result.get(
                            "message",
                            "No chat history available for the specified period",
                        ),
                        "data": None,
                        "format": "json",
                        "empty": True,
                    }

                return {
                    "success": True,
                    "message": result.get("message", "Export completed"),
                    "data": items,  # Return the grouped items
                    "format": "json",
                    "empty": False,
                }
            else:
                # File download (CSV, Word, PDF)
                # Return the raw bytes for download
                return {
                    "success": True,
                    "message": "Export file ready",
                    "data": response.content,  # Raw file bytes
                    "format": export_format,
                    "content_type": content_type,
                    "empty": False,
                }
        else:
            error_message = f"Error exporting chat history: {response.status_code} - {response.text}"
            logger.error(error_message)
            return {
                "success": False,
                "error": error_message,
                "data": None,
            }

    except requests.exceptions.RequestException as e:
        error_message = f"Request error exporting chat history: {str(e)}"
        logger.error(error_message)
        return {
            "success": False,
            "error": error_message,
            "data": None,
        }
    except Exception as e:
        error_message = f"Unexpected error exporting chat history: {str(e)}"
        logger.exception(error_message)
        return {
            "success": False,
            "error": error_message,
            "data": None,
        }


def get_session_messages(user_id: str, session_id: str) -> list:
    """
    Get all messages for a specific session by calling the backend session details endpoint.

    Args:
        user_id (str): The ID of the user
        session_id (str): The session ID

    Returns:
        list: All messages for the session, sorted by timestamp
    """
    try:
        auth_token = st.session_state.get("id_token", "")
        headers = settings.build_headers(None, auth_token)

        url = f"{settings.backend_base_url}/v1/session/{session_id}"

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            result = response.json()

            if result.get("success") and result.get("data"):
                session_data = result["data"]

                # Check if messages are included in the response
                if "messages" in session_data:
                    messages = session_data["messages"]
                    return sorted(messages, key=lambda x: x.get("created_at", ""))
                else:
                    logger.warning(
                        "[WARN] Backend session details endpoint doesn't include messages"
                    )
                    logger.debug("[CHART] Available session data: %s", session_data)
                    # The backend has the messages but doesn't return them
                    # We need to modify the backend to include messages in the response
                    return []
            else:
                logger.error(
                    "[ERROR] Session details API response missing success/data: %s",
                    result,
                )
                return []

        elif response.status_code == 404:
            logger.warning("[ERROR] Session %s not found", session_id)
            return []
        elif response.status_code == 403:
            logger.warning("[ERROR] Access denied for session %s", session_id)
            return []
        else:
            logger.error(
                "[ERROR] Session details API error: %s - %s",
                response.status_code,
                response.text,
            )
            return []

    except Exception:
        logger.exception("[ERROR] Error calling session details API")
        return []


def create_session_share(session_id: str, expires_in_days: int = 30) -> Dict[str, Any]:
    """
    Create a shareable link for a session.

    Args:
        session_id (str): The session ID to share
        expires_in_days (int): Number of days until share link expires (default: 30)

    Returns:
        Dict[str, Any]: Response indicating success or failure
            Example success: {
                "success": True,
                "share_token": "token_string",
                "expires_at": "2024-01-01T00:00:00Z",
                "message": "Session share link created successfully"
            }
            Example error: {
                "success": False,
                "message": "Error message"
            }
    """
    try:
        auth_token = st.session_state.get("id_token", "")
        headers = settings.build_headers(None, auth_token)

        url = f"{settings.backend_base_url}/v1/session/{session_id}/share"

        # Optional payload for expiration days
        payload = {"expires_in_days": expires_in_days} if expires_in_days else None

        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 200:
            result = response.json()
            return {
                "success": result.get("success", False),
                "share_token": result.get("share_token", ""),
                "expires_at": result.get("expires_at", ""),
                "message": result.get("message", "Share link created successfully"),
            }
        else:
            error_message = (
                f"Failed to create share link: {response.status_code} - {response.text}"
            )
            logger.error(error_message)
            return {
                "success": False,
                "message": error_message,
            }

    except requests.exceptions.RequestException as e:
        error_message = f"Request error creating share link: {str(e)}"
        logger.error(error_message)
        return {
            "success": False,
            "message": error_message,
        }
    except Exception as e:
        error_message = f"Unexpected error creating share link: {str(e)}"
        logger.exception(error_message)
        return {
            "success": False,
            "message": error_message,
        }


STREAM_IMAGE_CHUNK = 256 * 1024  # 256KB keeps memory low while downloading images


def get_image(image_path: str) -> Dict[str, Any]:
    """
    Retrieve an image from the backend image endpoint.

    Args:
        image_path (str): The image path/blob name to retrieve

    Returns:
        Dict[str, Any]: Response containing image data or error information
            Example success: {
                "success": True,
                "content": bytes,
                "content_type": "image/png",
                "filename": "image.png"
            }
            Example error: {
                "success": False,
                "error": "Error message",
                "status_code": 404
            }
    """
    try:
        auth_token = st.session_state.get("id_token", "")
        headers = settings.build_headers(None, auth_token)

        # Replace / with : to avoid APIM routing issues
        encoded_image_path = image_path.replace("/", "~")

        url = f"{settings.backend_base_url}/v1/image/{encoded_image_path}"

        with requests.get(url, headers=headers, timeout=30, stream=True) as response:
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "image/png")
                content_disposition = response.headers.get("content-disposition", "")

                # Extract filename from Content-Disposition header if available
                filename = "image"
                if "filename=" in content_disposition:
                    filename = content_disposition.split("filename=")[1].strip('"')
                else:
                    # Fallback to extracting from image_path
                    filename = (
                        image_path.split("/")[-1] if "/" in image_path else image_path
                    )

                buffer = bytearray()
                for chunk in response.iter_content(STREAM_IMAGE_CHUNK):
                    if chunk:
                        buffer.extend(chunk)

                return {
                    "success": True,
                    "content": bytes(buffer),
                    "content_type": content_type,
                    "filename": filename,
                }
            else:
                error_message = (
                    f"Error fetching image: {response.status_code} - {response.text}"
                )
                logger.error(error_message)
                return {
                    "success": False,
                    "error": error_message,
                    "status_code": response.status_code,
                }

    except requests.exceptions.RequestException as e:
        error_message = f"Request error fetching image: {str(e)}"
        logger.error(error_message)
        return {
            "success": False,
            "error": error_message,
            "status_code": None,
        }
    except Exception as e:
        error_message = f"Unexpected error fetching image: {str(e)}"
        logger.exception(error_message)
        return {
            "success": False,
            "error": error_message,
            "status_code": None,
        }
