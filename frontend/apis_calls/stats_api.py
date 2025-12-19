"""
API calls for bot statistics endpoints
"""

import requests
import logging
from typing import Dict, Any, Optional

try:
    from frontend.settings import settings
except Exception:
    from settings import settings

logger = logging.getLogger(__name__)

TIMEOUT = 30


def get_bot_statistics(
    bot_id: str, time_range: str = "today", headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Get bot statistics for a specific time period.

    Args:
        bot_id: The bot identifier
        time_range: Time period filter - 'today', 'this_week', or 'this_month'
        headers: Optional HTTP headers (for authentication)

    Returns:
        Dict containing:
        - success: Boolean indicating if the operation succeeded
        - data: Dict with bot statistics (total_messages, total_active_users, etc.)
        - error: Error message if operation failed
    """
    try:
        # Validate time_range parameter
        valid_ranges = ["today", "this_week", "this_month"]
        if time_range not in valid_ranges:
            return {
                "success": False,
                "error": f"Invalid time_range '{time_range}'. Must be one of: {', '.join(valid_ranges)}",
            }

        # Validate bot_id
        if not bot_id or not isinstance(bot_id, str):
            return {"success": False, "error": "bot_id must be a non-empty string"}

        # Construct URL and parameters
        url = f"{settings.backend_base_url}/v1/bots/{bot_id}/statistics"
        params = {"time_range": time_range}

        # Use create_headers if no headers provided
        request_headers = headers or settings.build_headers()

        # Make HTTP GET request
        response = requests.get(
            url, params=params, headers=request_headers, timeout=TIMEOUT
        )

        if response.status_code == 200:
            result = response.json()

            # Extract statistics data
            if result.get("success") and "data" in result:
                stats_data = result["data"]

                return {"success": True, "data": stats_data}
            else:
                error_msg = result.get("message", "Unknown error in response")
                logger.error(f"[ERROR] [STATS API] API returned error: {error_msg}")
                return {"success": False, "error": error_msg}
        else:
            # Handle HTTP error responses
            try:
                error_response = response.json()
                error_msg = error_response.get(
                    "message", f"HTTP {response.status_code}"
                )
            except (ValueError, TypeError, KeyError):
                error_msg = f"HTTP {response.status_code}: {response.text}"

            logger.error(f"[ERROR] [STATS API] HTTP error: {error_msg}")
            return {"success": False, "error": error_msg}

    except requests.exceptions.ConnectionError as e:
        error_msg = f"Connection error: {str(e)}. Backend service may not be running."
        logger.error(f"[ERROR] [STATS API] {error_msg}")
        return {"success": False, "error": error_msg}
    except requests.exceptions.Timeout as e:
        error_msg = f"Timeout error: {str(e)}. Request took too long."
        logger.error(f"[ERROR] [STATS API] {error_msg}")
        return {"success": False, "error": error_msg}
    except requests.exceptions.RequestException as e:
        error_msg = f"Request error: {str(e)}"
        logger.error(f"[ERROR] [STATS API] {error_msg}")
        return {"success": False, "error": error_msg}
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"[ERROR] [STATS API] {error_msg}")
        logger.exception("Full exception details:")
        return {"success": False, "error": error_msg}
