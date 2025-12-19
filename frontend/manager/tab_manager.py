import logging

import streamlit as st  # type: ignore
import uuid

try:
    from settings import settings
except ImportError:
    settings = None

logger = logging.getLogger(__name__)

Bot_ID = settings.bot_id
user_id = st.session_state.get("user_id")


# there should never be a reason for this function to be called
def get_session_title(session_id: str, messages: list, user_id: str) -> str:
    """
    Generates a title for a session from its messages as a fallback.
    """
    if messages and len(messages) > 0:
        first_message = messages[0]
        query_text = first_message.get("query", "")
        if query_text:
            words = query_text.split()[:3]
            title = " ".join(words)
            if len(query_text.split()) > 3:
                title += "..."
            return title

    return f"Session {session_id[-8:]}"


def init_state():
    if "open_tabs" not in st.session_state:
        st.session_state["open_tabs"] = []
    if "tab_messages" not in st.session_state:
        st.session_state["tab_messages"] = {}
    if "active_tab_index" not in st.session_state:
        st.session_state["active_tab_index"] = 0

    # Ensure there's always at least one tab open
    if not st.session_state["open_tabs"]:
        add_new_tab(user_id=user_id)

    # Ensure active tab index is valid
    if st.session_state["active_tab_index"] >= len(st.session_state["open_tabs"]):
        st.session_state["active_tab_index"] = max(
            0, len(st.session_state["open_tabs"]) - 1
        )


def add_new_tab(user_id: str, session_id: str = None, title: str = None):
    """Add a new tab for either a new chat or existing session"""
    if len(st.session_state["open_tabs"]) >= settings.max_tabs:
        st.error(f"Maximum {settings.max_tabs} tabs allowed. Please close a tab first.")
        return False

    # Check if tab already exists
    for tab in st.session_state["open_tabs"]:
        if tab["session_id"] == session_id:
            return False

    if session_id is None:
        # Create completely new session
        session_id = f"session_{uuid.uuid4().hex[:8]}"
        title = "New Chat"
        st.session_state["tab_messages"][session_id] = []
    else:
        # Load existing session messages (only for existing sessions)
        messages = load_existing_session_messages(session_id, user_id)
        st.session_state["tab_messages"][session_id] = messages
        if title is None:
            title = get_session_title(session_id, messages, user_id)

    # Add the new tab
    st.session_state["open_tabs"].append({"session_id": session_id, "title": title})

    # Set the new tab as active (it will be the last one in the list)
    st.session_state["active_tab_index"] = len(st.session_state["open_tabs"]) - 1

    return True


def load_existing_session_messages(session_id, user_id):
    """
    Load messages for an existing session directly from the backend API.

    Args:
        session_id (str): Session ID to load messages for
        user_id (str): User ID

    Returns:
        list: List of messages, empty list if none found or error occurs
    """
    try:
        logger.info("Loading messages for session: %s", session_id)

        from apis_calls.session_apis import get_session_messages

        backend_messages = get_session_messages(user_id, session_id)

        if backend_messages:
            return backend_messages
        else:
            logger.warning(
                "[ERROR] No messages returned from backend for session %s", session_id
            )
            return []

    except Exception:
        logger.exception("[ERROR] Error loading messages for session %s", session_id)
        return []


def _cleanup_active_session_state(session_id):
    """
    Clean up active session state when closing tabs.

    Args:
        session_id (str): Session ID to clean up from active state
    """
    # Remove from active tab messages
    if session_id in st.session_state.get("tab_messages", {}):
        del st.session_state["tab_messages"][session_id]

    # Remove any tab-specific chat drafts
    if (
        "tab_chat_drafts" in st.session_state
        and session_id in st.session_state["tab_chat_drafts"]
    ):
        del st.session_state["tab_chat_drafts"][session_id]

    # Clean up any chat input state for this session
    chat_input_key = f"chat_input_{session_id}"
    if chat_input_key in st.session_state:
        del st.session_state[chat_input_key]

    # Clean up any FAQ flags for this session
    faq_flag_key = f"faq_just_clicked_{session_id}"
    if faq_flag_key in st.session_state:
        del st.session_state[faq_flag_key]

    # Clean up any other session-specific state
    keys_to_remove = [key for key in st.session_state.keys() if session_id in key]
    for key in keys_to_remove:
        if key not in [
            f"chat_input_{session_id}",
            f"faq_just_clicked_{session_id}",
        ]:  # Already handled above
            try:
                del st.session_state[key]
            except KeyError:
                pass  # Key already removed


def close_tab(index: int, user_id: str):
    """
    Close a tab by index. Prevents closing the last remaining tab.

    Args:
        index (int): Index of the tab to close

    Returns:
        bool: True if tab was successfully closed, False otherwise
    """

    # Validate index
    if not (0 <= index < len(st.session_state.get("open_tabs", []))):
        logger.warning("[ERROR] Invalid index %s", index)
        return False

    # If closing the last tab, create a new one first
    if len(st.session_state["open_tabs"]) <= 1:
        # Get the session_id of the tab being closed for cleanup
        session_id_to_close = st.session_state["open_tabs"][0]["session_id"]

        # Create a new tab first
        new_session_id = f"session_{uuid.uuid4().hex[:8]}"
        st.session_state["open_tabs"] = [
            {"session_id": new_session_id, "title": "New Chat"}
        ]
        st.session_state["tab_messages"][new_session_id] = []
        st.session_state["active_tab_index"] = 0

        # Clean up the old session
        _cleanup_active_session_state(session_id_to_close)

        # Clear any segmented control cached state
        keys_to_remove = [
            key for key in st.session_state.keys() if key.startswith("tab_selector_")
        ]
        for key in keys_to_remove:
            del st.session_state[key]

        # Ensure active tab index is correct
        st.session_state["active_tab_index"] = 0

        return True

    # Get tab info before removal
    tab_to_close = st.session_state["open_tabs"][index]
    session_id = tab_to_close["session_id"]

    # Adjust active tab index BEFORE removal
    current_active = st.session_state.get("active_tab_index", 0)
    total_tabs_before_removal = len(st.session_state["open_tabs"])

    if current_active == index:
        # Closing the currently active tab
        if index == total_tabs_before_removal - 1:
            # Closing the last tab, move to previous
            st.session_state["active_tab_index"] = max(0, index - 1)
        # If not the last tab, keep same index (next tab will slide into this position)
    elif current_active > index:
        # Active tab is after the one being closed, shift left
        st.session_state["active_tab_index"] = current_active - 1

    # Remove tab from open tabs list
    st.session_state["open_tabs"].pop(index)

    # Clean up active session state
    _cleanup_active_session_state(session_id)

    # Mark session as recently closed to prevent immediate reopening
    recently_closed_key = f"recently_closed_{session_id}"
    st.session_state[recently_closed_key] = True

    # Clear any segmented control cached state and update with new active index
    keys_to_remove = [
        key for key in st.session_state.keys() if key.startswith("tab_selector_")
    ]
    for key in keys_to_remove:
        del st.session_state[key]

    # Force update of the active tab index to prevent random tab opening
    # This ensures the segmented control will be initialized with the correct active tab
    new_active_index = st.session_state.get("active_tab_index", 0)
    if new_active_index >= len(st.session_state["open_tabs"]):
        st.session_state["active_tab_index"] = max(
            0, len(st.session_state["open_tabs"]) - 1
        )

    return True


def update_tab_title(tab_index, new_title):
    """Update the title of a tab"""
    if 0 <= tab_index < len(st.session_state["open_tabs"]):
        st.session_state["open_tabs"][tab_index]["title"] = new_title


def start_new_chat_in_active_tab():
    """Replaces the active tab with a new, empty chat session."""
    active_tab_info = get_active_tab_info()
    if not active_tab_info:
        add_new_tab(user_id="default_user")  # Create one if none exist
        return

    active_index = active_tab_info["index"]
    old_session_id = active_tab_info["session_id"]

    # Generate new session ID for the active tab
    new_session_id = f"session_{uuid.uuid4().hex[:8]}"

    # Update the active tab with new session
    st.session_state["open_tabs"][active_index]["session_id"] = new_session_id
    st.session_state["open_tabs"][active_index]["title"] = "New Chat"

    # Clear messages for the new session
    st.session_state["tab_messages"][new_session_id] = []

    # Clean up old session data
    _cleanup_active_session_state(old_session_id)


def open_session(session_id: str, session_title: str, user_id: str):
    """
    Opens a session: switches to it if already open,
    or adds it as a new tab.
    """
    # 1. Check if session is already open in a tab
    for i, tab in enumerate(st.session_state["open_tabs"]):
        if tab["session_id"] == session_id:
            # Session already open, just switch to that tab
            st.session_state["active_tab_index"] = i
            return True

    # 2. Check if we've reached max tabs
    if len(st.session_state.get("open_tabs", [])) >= settings.max_tabs:
        st.error(f"Maximum {settings.max_tabs} tabs allowed. Please close a tab first.")
        return False

    # 3. Session is not open, add it as a new tab
    return add_new_tab(user_id, session_id, session_title)


def get_active_tab_info():
    """
    Get information about the currently active tab
    Returns dict with session_id, title, and index, or None if no tabs
    """
    if (
        "open_tabs" not in st.session_state
        or not st.session_state["open_tabs"]
        or "active_tab_index" not in st.session_state
    ):
        return None

    active_index = st.session_state.get("active_tab_index", 0)
    if 0 <= active_index < len(st.session_state["open_tabs"]):
        tab_data = st.session_state["open_tabs"][active_index]
        return {
            "session_id": tab_data["session_id"],
            "title": tab_data["title"],
            "index": active_index,
        }

    return None
