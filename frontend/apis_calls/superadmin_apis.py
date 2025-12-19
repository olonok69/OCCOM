import logging
import time
import base64

import requests
import streamlit as st  # type: ignore

try:
    from frontend.settings import settings
except Exception:
    from settings import settings


logger = logging.getLogger(__name__)


def get_bot_config():
    """Get bot configuration from backend API only. Returns None on error to prevent Streamlit crashes."""
    try:
        auth_token = st.session_state.get("id_token", "")
        HEADERS = settings.build_headers(None, auth_token)
        BACKEND_API_BASE_URL = settings.backend_base_url

        # Add no-cache header and a cache-busting query param to avoid stale assets
        HEADERS["Cache-Control"] = "no-cache"
        response = requests.get(
            f"{BACKEND_API_BASE_URL}/v1/config",
            headers=HEADERS,
            params={"_ts": int(time.time())},
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json().get("config") or {}
            # --- Update session-state image bytes from response 'images' ---
            # Backend should include: {"images": {"logo_file_name": "<b64>", "bot_icon_name": "<b64>", "user_icon_name": "<b64>"}}
            try:
                images = data.get("images") or {}
                # Always replace branding_bytes to avoid stale cache
                new_brand = {}
                mapping = [
                    ("logo_base64", "logo"),
                    ("bot_icon_base64", "bot_icon"),
                    ("user_icon_base64", "user_icon"),
                ]
                for cfg_key, sess_key in mapping:
                    b64 = images.get(cfg_key)
                    if not b64:
                        continue
                    raw = b64.split(",", 1)[-1] if "," in b64 else b64
                    try:
                        new_brand[sess_key] = base64.b64decode(raw)
                    except Exception:
                        # Ignore malformed base64
                        pass
                st.session_state["branding_bytes"] = new_brand
            except Exception:
                # Do not break config load if images processing fails
                logger.exception("[get_bot_config] branding_bytes update skipped")

            return data

        else:
            error_msg = f"Failed to get config from backend: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return None

    except requests.exceptions.Timeout as e:
        error_message = f"Request timeout fetching bot config: {str(e)}"
        logger.error(error_message)
        return None
    except requests.exceptions.RequestException as e:
        logger.error("Error getting bot config from API: %s", e)
        return None
    except Exception as e:
        logger.exception("Unexpected error getting bot config: %s", e)
        return None


def update_bot_config(new_config):
    """Update bot configuration via backend API only"""
    try:
        HEADERS = settings.build_headers(None, None)
        BACKEND_API_BASE_URL = settings.backend_base_url

        # Send bot_id as query parameter and config as body
        response = requests.put(
            f"{BACKEND_API_BASE_URL}/v1/updateconfig",
            json=new_config,
            headers=HEADERS,
        )

        if response.status_code == 200:
            return response.json().get("config", {})
        else:
            error_msg = f"Failed to update config via backend: {response.status_code} - {response.text}"
            logger.error(error_msg)
            raise requests.exceptions.HTTPError(error_msg)

    except requests.exceptions.Timeout as e:
        error_message = f"Request timeout updating bot config: {str(e)}"
        logger.error(error_message)
        return None
    except requests.exceptions.RequestException as e:
        logger.error("Error updating bot config via API: %s", e)
        raise
    except Exception as e:
        logger.exception("Unexpected error updating bot config: %s", e)
        raise


def save_image_to_storage(image_type: str, file_obj) -> dict:
    """
    Send image bytes as base64 to backend PUT /v1/updateconfig.
    `image_type` must be one of: "logo", "bot_icon", "user_icon".
    Returns backend JSON.
    """

    # Read all bytes from Streamlit UploadedFile
    raw_bytes = file_obj.getvalue()
    b64 = base64.b64encode(raw_bytes).decode("utf-8")

    # Standard headers you already use
    auth_token = st.session_state.get("id_token", "")
    HEADERS = settings.build_headers(None, None)
    if auth_token and "Authorization" not in HEADERS:
        HEADERS["Authorization"] = f"Bearer {auth_token}"
    HEADERS["Content-Type"] = "application/json"

    BASE_URL = settings.backend_base_url

    # Map image_type to payload fields
    key_map = {
        "logo": ("logo_image_base64", "logo_filename"),
        "bot_icon": ("bot_icon_image_base64", "bot_icon_filename"),
        "user_icon": ("user_icon_image_base64", "user_icon_filename"),
    }
    if image_type not in key_map:
        return {"success": False, "message": f"unknown image_type: {image_type}"}

    b64_key, name_key = key_map[image_type]
    payload = {
        b64_key: b64,
        name_key: getattr(file_obj, "name", f"{image_type}.png"),
    }

    # PUT /v1/updateconfig with minimal body
    resp = requests.put(
        f"{BASE_URL}/v1/updateconfig", json=payload, headers=HEADERS, timeout=60
    )
    try:
        return resp.json()
    except Exception:
        return {"success": False, "status": resp.status_code, "text": resp.text}


def factory_reset():
    """
    Perform factory reset - delete all files, images, search index, and reset config.

    This is a destructive operation that requires FACTORY_RESET_BOT=true in backend.

    Returns:
        dict: Response from the backend with success status and details
    """
    try:
        auth_token = st.session_state.get("id_token", "")
        HEADERS = settings.build_headers(None, auth_token)
        BACKEND_API_BASE_URL = settings.backend_base_url

        # Make DELETE request to factory reset endpoint
        response = requests.delete(
            f"{BACKEND_API_BASE_URL}/v1/reset-factory-new",
            headers=HEADERS,
            timeout=120,  # Longer timeout as this can take a while
        )
        if response.status_code == 200:
            return {
                "success": True,
                "data": response.json(),
                "message": "Factory reset completed successfully",
            }
        elif response.status_code == 403:
            return {
                "success": False,
                "error": "Factory reset is disabled. Set FACTORY_RESET_BOT=true in backend environment.",
                "status_code": 403,
            }
        else:
            error_msg = (
                f"Factory reset failed: {response.status_code} - {response.text}"
            )
            return {
                "success": False,
                "error": error_msg,
                "status_code": response.status_code,
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Factory reset request timed out. The operation may still be in progress.",
        }
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"Error performing factory reset: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}"}
