"""
Public page for viewing shared sessions without authentication.

This page can be accessed via: /shared?session_id=abc123xyz
No authentication required. Session must be marked as public on backend.
"""

import streamlit as st
import requests
import base64
from navigation.pdf_viewer import display_citations_with_viewer
from components.ui_components_chat import safe_display_image_thumbnail
from apis_calls.superadmin_apis import get_bot_config

from settings import settings

try:
    from st_copy import copy_button
except ImportError:
    copy_button = None  # Fallback if package not installed

st.set_page_config(page_title="Shared Session", layout="wide")

import logging

BACKEND_API_BASE_URL = settings.backend_base_url if settings else None
logger = logging.getLogger(__name__)
FRONT_EXCEPTION_TAG = "FRONT_EXCEPTION"


def get_shared_session(session_id: str):
    """
    Fetch shared session data from backend API (no auth required).
    Calls the public session endpoint.

    Args:
        session_id: Session ID from URL

    Returns:
        Dict with session data or None if error
    """
    try:
        url = f"{BACKEND_API_BASE_URL}/v1/public_session/{session_id}"
        # Use settings.build_headers() to include APIM subscription key
        headers = settings.build_headers() if settings else {}
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                return result.get("data")
            logger.warning(
                "%s shared_session.api_returned_failure session_id=%s message=%s",
                FRONT_EXCEPTION_TAG,
                session_id,
                result.get("error"),
            )
        else:
            logger.warning(
                "%s shared_session.api_status_%s session_id=%s",
                FRONT_EXCEPTION_TAG,
                response.status_code,
                session_id,
            )
        return None
    except Exception as e:
        logger.exception("%s shared_session.fetch_failed", FRONT_EXCEPTION_TAG)
        st.error(f"Error fetching shared session: {str(e)}")
        return None


def render_shared_session(session_id: str):
    """
    Render the shared session in read-only mode.

    Args:
        session_id: Session ID from URL
    """
    # Load bot config to get logo and icons
    try:
        get_bot_config()
    except Exception:
        logger.exception(
            "%s shared_session.bot_config_fetch_failed", FRONT_EXCEPTION_TAG
        )
        # Continue even if config load fails

    # Display bot logo at the top
    branding = st.session_state.get("branding_bytes", {})
    center_logo = branding.get("logo") or branding.get("bot_icon")
    if center_logo:
        try:
            b64 = base64.b64encode(center_logo).decode("utf-8")
            st.markdown(
                f"""
                <div style='text-align:center;margin: 0.5rem 0 0.75rem;'>
                  <img src="data:image/png;base64,{b64}" alt="logo" style="display:block;margin:0 auto;width:120px;" />
                </div>
                """,
                unsafe_allow_html=True,
            )
        except Exception:
            logger.exception(
                "%s shared_session.logo_render_failed", FRONT_EXCEPTION_TAG
            )
            # Fallback if bytes are not as expected
            _, c, _ = st.columns([1, 2, 1])
            with c:
                st.image(center_logo, width=120)

    # Fetch session data
    session_data = get_shared_session(session_id)

    if not session_data:
        logger.warning(
            "%s shared_session.no_data session_id=%s",
            FRONT_EXCEPTION_TAG,
            session_id,
        )
        st.error("❌ Shared session not found or expired.")
        st.info("The share link may have expired or been revoked.")
        return

    # Display header
    st.title("📤 Shared Session")
    st.info("🔒 This is a read-only view of a shared chat session.")

    # Session metadata
    messages = session_data.get("messages", [])
    message_count = session_data.get("message_count", len(messages))
    created_at = session_data.get("created_at", "Unknown")
    last_activity = session_data.get("last_activity", "Unknown")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Messages", message_count)
    with col2:
        st.metric("Created", created_at[:10] if len(created_at) > 10 else created_at)
    with col3:
        st.metric(
            "Last Activity",
            last_activity[:10] if len(last_activity) > 10 else last_activity,
        )

    st.divider()

    # Display messages
    if not messages:
        st.warning("This session has no messages.")
        return

    st.subheader("💬 Conversation")

    # Get avatars from branding_bytes
    user_avatar = branding.get("user_icon") or "👤"
    bot_avatar = branding.get("bot_icon") or "🤖"

    # Render messages in a scrollable container
    with st.container(height=600, border=True):
        for msg_idx, message in enumerate(messages):
            # User message
            with st.chat_message("user", avatar=user_avatar):
                st.write(message.get("query", ""))

            # Assistant response
            with st.chat_message("assistant", avatar=bot_avatar):
                response_text = message.get("response", "")
                st.write(response_text)

                # Copy button for bot response
                if copy_button:
                    copy_button(response_text)
                else:
                    st.caption("Install st-copy for copy button")

                # Citations
                citations = message.get("citations", [])
                if citations:
                    display_citations_with_viewer(
                        citations,
                        message_id=f"shared_{msg_idx}",
                    )

                # Images
                images = message.get("images", [])
                if images:
                    st.write("**Images:**")
                    if len(images) == 1:
                        safe_display_image_thumbnail(images[0], "Reference Image")
                    else:
                        cols = st.columns(min(len(images), 3))
                        for idx, image_data in enumerate(images):
                            with cols[idx % 3]:
                                safe_display_image_thumbnail(
                                    image_data, f"Image {idx + 1}"
                                )

    st.divider()
    st.caption("💡 This is a shared session. You cannot interact with it.")


# Main page logic - executed when page loads
# Get session_id from query params or session state
session_id = None

# Method 1: Try query parameters
try:
    query_params = st.query_params
    if query_params:
        session_id = query_params.get("session_id")
except Exception:
    logger.exception("%s shared_session.query_params_error", FRONT_EXCEPTION_TAG)

# Method 2: Check session state (preserved from main.py)
if not session_id:
    session_id = st.session_state.get("shared_session_id")

if not session_id:
    st.error("❌ No session ID provided.")
    st.info("Please use a valid share link to view a shared session.")
    st.code("Example: /shared?session_id=abc123xyz")
    st.info(
        "💡 Make sure you're using the full share URL with the session_id parameter."
    )
    # Debug info
    try:
        st.json(
            {
                "query_params": dict(st.query_params) if st.query_params else {},
                "session_state_id": st.session_state.get("shared_session_id"),
            }
        )
    except Exception:
        logger.exception(
            "%s shared_session.debug_payload_render_failed", FRONT_EXCEPTION_TAG
        )
else:
    # Preserve session_id in session state for next render
    st.session_state["shared_session_id"] = session_id
    # Render the shared session
    render_shared_session(session_id)
