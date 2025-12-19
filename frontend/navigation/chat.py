import streamlit as st
import base64
from components.session_sidebar import render_session_sidebar
from manager.tab_manager import (
    init_state,
    get_active_tab_info,
    add_new_tab,
    close_tab,
    open_session,
    start_new_chat_in_active_tab,
)
from components.ui_components_chat import render_main_content

try:
    from settings import settings
except ImportError:
    settings = None

st.set_page_config(page_title="Chat", layout="wide")

Bot_ID = settings.bot_id
user_id = st.session_state.get("user_id")

# --- 0. Page-level spacing (kept consistent with global 2rem) ---
st.markdown(
    """
    <style>
    .main .block-container { padding: 2rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- 1. Initialize State ---
init_state()

# --- 2. Handle Tab Close Signal ---
if "tab_to_close" in st.session_state:
    tab_index = st.session_state.pop("tab_to_close")
    if close_tab(tab_index, user_id=user_id):
        st.rerun()

# --- 3. Render Sidebar and Handle Signals ---
with st.sidebar:
    render_session_sidebar(user_id)

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
        # Fallback if bytes are not as expected
        _, c, _ = st.columns([1, 2, 1])
        with c:
            st.image(center_logo, width=120)

# Handle sidebar signals
if st.session_state.get("create_new_tab", False):
    st.session_state.pop("create_new_tab")
    if add_new_tab(user_id=user_id):
        st.rerun()

if st.session_state.get("start_new_chat_in_active_tab", False):
    st.session_state.pop("start_new_chat_in_active_tab")
    start_new_chat_in_active_tab()
    st.rerun()

if st.session_state.get("open_session_in_new_tab"):
    session_data = st.session_state.pop("open_session_in_new_tab")
    session_id = session_data["session_id"]
    session_title = session_data["title"]

    if open_session(session_id, session_title, user_id):
        if "dataframe_key_counter" not in st.session_state:
            st.session_state["dataframe_key_counter"] = 0
        st.session_state["dataframe_key_counter"] += 1
        st.rerun()

# --- 4. Render Main Content ---
# Get the *current* active tab after all state changes
active_tab = get_active_tab_info()

if active_tab:
    render_main_content(user_id=user_id, active_tab=active_tab)
else:
    st.warning("No active chats. Creating a new one.")
    if add_new_tab(user_id=user_id):
        st.rerun()
