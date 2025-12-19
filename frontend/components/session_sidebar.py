"""
Session sidebar component for displaying and selecting chat sessions.
This module also renders user welcome + logout controls in the sidebar.
"""

import logging
import os
import base64

import pandas as pd
import streamlit as st  # type: ignore
import re
from apis_calls.session_apis import (
    export_chat_history as export_chat_history_endpoint,
    get_session_titles,
)
from urllib.parse import quote


logger = logging.getLogger(__name__)


def remove_non_alpha_from_start(text):
    """Remove non-alphabetic characters from the start of a string."""
    return re.sub(r"^[^a-zA-Z]+", "", text)


def get_active_tab_session_id():
    """
    Get the session_id of the currently active tab
    Returns None if no tabs are open
    """
    if (
        "open_tabs" not in st.session_state
        or not st.session_state["open_tabs"]
        or "active_tab_index" not in st.session_state
    ):
        return None

    active_index = st.session_state.get("active_tab_index", 0)
    if 0 <= active_index < len(st.session_state["open_tabs"]):
        return st.session_state["open_tabs"][active_index]["session_id"]

    return None


def _render_logo_header(cfg: dict) -> None:
    """Render logo (centered) and bot name."""
    bot_name = cfg.get("bot_name", "Chat")
    st.markdown(
        """
        <style>
          .brand-name {
            text-align:center;
            font-size:22px;
            font-weight:700;
            margin: 6px 0 2px 0;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _, c, _ = st.columns([1, 2, 1])
    with c:
        bb = st.session_state.get("branding_bytes", {})
        logo = bb.get("logo")
        if logo:
            try:
                b64 = base64.b64encode(logo).decode("utf-8")
                st.markdown(
                    f"""
                    <div style='text-align:center;'>
                      <img src="data:image/png;base64,{b64}" style="display:block;margin:0 auto;width:110px;" />
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            except Exception:
                st.image(logo, width=110)
        else:
            st.markdown(
                "<div style='text-align:center;font-size:28px;'>🧩</div>",
                unsafe_allow_html=True,
            )
    st.markdown(
        f'<div class="brand-name";">{bot_name}</div>',
        unsafe_allow_html=True,
    )


def _render_user_header() -> None:
    """Render a compact user header with avatar and logout in sidebar."""
    username = st.session_state.get("username", "User")
    st.markdown(
        f'<div style="text-align:center;padding-top:20px;"><strong>Welcome {username}!</strong></div>',
        unsafe_allow_html=True,
    )

    def _logout():
        # Clear session and preserve bot_id from environment
        st.session_state.clear()
        st.session_state["bot_id"] = os.getenv("BOT_ID", "default")

    st.button(
        "Logout",
        help="Log out",
        on_click=_logout,
        width="stretch",
    )


def _render_about(cfg: dict) -> None:
    """Render About expander with optional inline feedback button."""
    about_text = cfg.get("about_text", "")
    email = cfg.get("feedback_contact_email")
    bot_name = cfg.get("bot_name", "Chat")
    secondary_bg = cfg.get("secondary_background_color", "rgba(255,255,255,0.08)")
    text_color = cfg.get("text_color", "#000")

    if not about_text and not email:
        return

    with st.expander("About", expanded=False, icon="ℹ️"):
        if about_text:
            st.markdown(
                f"<p style='font-size:14px; line-height:1.4;'>{about_text}</p>",
                unsafe_allow_html=True,
            )

        if email:
            st.subheader("Got questions? Please contact us:")
            subject = quote(f"Feedback for {bot_name}")
            mailto = f"mailto:{email}?subject={subject}"

            st.markdown(
                f"""
                <style>
                [data-testid="stSidebar"] .inline-feedback a {{
                    display:block; width:100%;
                    padding:8px 12px; text-align:center;
                    border-radius:8px; border:1px solid rgba(0,0,0,.15);
                    background:{secondary_bg}; color:{text_color};
                    text-decoration:none; font-weight:600;
                }}
                [data-testid="stSidebar"] .inline-feedback a:hover {{
                    filter:brightness(1.08);
                }}
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""<div class="inline-feedback"><a href="{mailto}">✉️ Send Feedback</a></div>""",
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)


def _render_external_links(cfg: dict) -> None:
    """Render External Links section."""
    links = cfg.get("external_links", [])
    if not links:
        return

    with st.expander("External Links", expanded=False, icon="🔗"):
        for link in links:
            title = link.get("title", "Link")
            url = link.get("url", "#")
            st.link_button(title, url, use_container_width=True)


def _render_faq(cfg: dict) -> None:
    """Render FAQ expander. Clicking a question sets it in the active tab's chat input."""
    faqs = cfg.get("faq") or []
    if not faqs:
        return

    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] .stButton > button {
            text-align:left !important;
            justify-content:flex-start !important;
            padding:3px 4px !important;
            margin-bottom:1px !important;
            display:flex !important;
            align-items:center !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("FAQ", expanded=False, icon="❓"):
        for i, question in enumerate(faqs, 1):
            # Remove non-alphabetic characters from the start (handles -, *, 1., ~, etc.)
            question_text = remove_non_alpha_from_start(question)
            if st.button(question, type="tertiary", key=f"faq_{i}", width="stretch"):
                active_session_id = get_active_tab_session_id()

                if active_session_id:
                    # Create per-tab chat input key
                    chat_input_key = f"chat_input_{active_session_id}"
                    st.session_state[chat_input_key] = question_text
                    flag_key = f"faq_just_clicked_{active_session_id}"
                    st.session_state[flag_key] = True
                st.rerun()


def _render_disclaimer(cfg: dict) -> None:
    """Render Disclaimer expander."""
    text = cfg.get("disclaimer_text", "")
    if not text:
        return
    with st.expander("Disclaimer", expanded=False, icon="⚠️"):
        st.markdown(
            f"<p style='font-size:14px; line-height:1.4;'>{text}</p>",
            unsafe_allow_html=True,
        )


def _load_changelog_data():
    """Load changelog data from JSON file."""
    import json
    import os

    current_dir = os.path.dirname(os.path.abspath(__file__))
    changelog_path = os.path.join(current_dir, "..", "changelog.json")
    changelog_path = os.path.normpath(changelog_path)

    try:
        with open(changelog_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"current_version": "0.0.0", "changelog": []}


def _format_date(date_str):
    """Format date string to readable format."""
    from datetime import datetime

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj.strftime("%B %d, %Y")
    except ValueError:
        return date_str


@st.dialog("📋 Change Log", width="large")
def show_changelog_dialog():
    """Display changelog in a modal dialog."""
    data = _load_changelog_data()
    current_version = data.get("current_version", "0.0.0")
    changelog_entries = data.get("changelog", [])

    # Render each version entry
    if not changelog_entries:
        st.warning("⚠️ No changelog entries available.")
        return

    # Sort entries by date (newest first) for display
    sorted_entries = sorted(
        changelog_entries, key=lambda x: x.get("date", ""), reverse=True
    )

    # Display all releases
    for entry in sorted_entries:
        version = entry.get("version", "")
        date = entry.get("date", "")
        label = entry.get("label", "")
        features = entry.get("features", [])
        bugfixes = entry.get("bugfixes", [])

        formatted_date = _format_date(date) if date else ""

        # Determine release title
        if version == current_version:
            release_title = f"Current Release: Version {version}"
        elif label == "Initial Release":
            release_title = f"Initial Release: Version {version}"
        else:
            release_title = f"Version {version}"

        # Build items HTML (features and bugfixes combined, no headings)
        items_html = ""
        item_counter = 1

        if features or bugfixes:
            items_html = "<div style='margin-left: 0.5rem; margin-top: 0.5rem;'>"

            # Add features
            for feature in features:
                if isinstance(feature, str):
                    feature_text = feature
                    if feature_text.strip():
                        items_html += f"<div style='margin-bottom: 0.75rem;'><strong>{item_counter}. {feature_text}</strong></div>"
                        item_counter += 1
                else:
                    title = feature.get("title", "")
                    description = feature.get("description", "")
                    if title:
                        items_html += f"<div style='margin-bottom: 0.75rem;'><strong>{item_counter}. {title}</strong>"
                        if description:
                            items_html += f"<div style='margin-left: 1.5rem; margin-top: 0.25rem; color: #555; line-height: 1.5;'>{description}</div>"
                        items_html += "</div>"
                        item_counter += 1

            # Add bugfixes
            for bugfix in bugfixes:
                if isinstance(bugfix, str):
                    bugfix_text = bugfix
                    if bugfix_text.strip():
                        items_html += f"<div style='margin-bottom: 0.75rem;'><strong>{item_counter}. {bugfix_text}</strong></div>"
                        item_counter += 1
                else:
                    title = bugfix.get("title", "")
                    description = bugfix.get("description", "")
                    if title:
                        items_html += f"<div style='margin-bottom: 0.75rem;'><strong>{item_counter}. {title}</strong>"
                        if description:
                            items_html += f"<div style='margin-left: 1.5rem; margin-top: 0.25rem; color: #555; line-height: 1.5;'>{description}</div>"
                        items_html += "</div>"
                        item_counter += 1

            items_html += "</div>"

        # Display release box with all content inside
        st.markdown(
            f"""
            <div style="background-color: #f8f9fa; padding: 1rem; border-radius: 6px; border: 1px solid #e0e0e0; margin-bottom: 1rem;">
                <div style="font-size: 1.2em; font-weight: 600; margin-bottom: 0.5rem;">{release_title}</div>
                {f'<div style="color: #666; font-size: 0.9em; margin-bottom: 1rem;">📅 {formatted_date}</div>' if formatted_date else '<div style="margin-bottom: 1rem;"></div>'}
                {items_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Footer note with better spacing
    st.markdown("<div style='margin-top: 2rem;'></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)


def _render_version_footer() -> None:
    """Render version link at the bottom of the sidebar."""
    import json
    import os

    # Get the path to changelog.json
    current_dir = os.path.dirname(os.path.abspath(__file__))
    changelog_path = os.path.join(current_dir, "..", "changelog.json")
    changelog_path = os.path.normpath(changelog_path)

    # Load current version
    try:
        with open(changelog_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            version = data.get("current_version", "0.0.0")
    except (FileNotFoundError, json.JSONDecodeError):
        version = "0.0.0"

    # Add spacing and styling
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .version-footer {
            text-align: center;
            padding: 0.75rem 0;
            margin-top: auto;
            border-top: 1px solid rgba(250, 250, 250, 0.2);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Create clickable version link that opens modal dialog
    if st.button(f"Version {version}", key="version_link", use_container_width=True):
        show_changelog_dialog()


def refresh_session_titles():
    """
    Refresh session titles from the backend and update the cache.
    This should be called after creating new sessions.
    """
    try:
        titles_result = get_session_titles()
        if titles_result and titles_result.get("success"):
            st.session_state["cached_session_titles"] = titles_result.get(
                "session_titles", {}
            )
        else:
            logger.warning("Failed to refresh session titles")
    except Exception:
        logger.exception("Error refreshing session titles")


def _render_past_sessions(
    user_id: str,
) -> None:
    """
    Render the session sidebar with session selection functionality.
    This component is now a "View" and only sets signals in st.session_state.
    The main chat.py "Controller" will catch and handle these signals.
    """
    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "➕ New Chat",
            help="Start new chat in current tab",
            width="stretch",
        ):
            # Signal to start new chat in current active tab
            st.session_state["start_new_chat_in_active_tab"] = True
            if "dataframe_key_counter" not in st.session_state:
                st.session_state["dataframe_key_counter"] = 0
            st.session_state["dataframe_key_counter"] += 1
            st.rerun()
    with col2:
        if st.button("📑 New Tab", help="Create new chat tab", width="stretch"):
            st.session_state["create_new_tab"] = True
            st.rerun()  # <--- [ADDED] Rerun to process signal
    ########################
    with st.popover("📤 Export Chat History", width="stretch"):
        st.subheader("Export Options")

        # Timeframe selection with display names
        timeframe_options = {
            "Last 24 Hours": "day",
            "Last Week": "week",
            "Last Month": "month",
            "Last 3 Months": "3month",
            "Last 6 Months": "6month",
            "All Time": "all",
        }

        timeframe_display = st.selectbox(
            "Select Timeframe",
            list(timeframe_options.keys()),
            index=1,
        )
        timeframe = timeframe_options[timeframe_display]

        # Format selection
        export_format = st.selectbox(
            "Export Format", ["PDF", "Word (DOCX)", "CSV"], index=0
        )

        # Export button
        if st.button("🚀 Export", type="primary", width="stretch"):
            # Get the date range based on selection
            date_range = timeframe

            # Map format selection to backend format
            format_mapping = {
                "PDF": "pdf",
                "Word (DOCX)": "docx",
                "CSV": "csv",  # Using CSV as text format
            }
            backend_format = format_mapping.get(export_format, "json")

            # Call export function
            with st.spinner("Exporting chat history..."):
                export_result = export_chat_history(
                    user_id=user_id,
                    period=date_range,
                    export_format=backend_format,
                )

            if export_result and export_result.get("success"):
                # Check if chat history is empty
                if export_result.get("empty"):
                    st.info("No chat history available for the specified period.")
                    return

                export_data = export_result.get("data")
                result_format = export_result.get("format", backend_format)

                if export_data:
                    # Determine file extension and MIME type
                    file_extension_map = {
                        "pdf": "pdf",
                        "docx": "docx",
                        "word": "docx",
                        "csv": "csv",
                        "json": "json",
                    }

                    mime_type_map = {
                        "pdf": "application/pdf",
                        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "csv": "text/csv",
                        "json": "application/json",
                    }

                    file_extension = file_extension_map.get(result_format, "txt")
                    mime_type = mime_type_map.get(result_format, "text/plain")
                    filename = f"chat_export_{timeframe}.{file_extension}"

                    st.download_button(
                        label=f"📥 Download {export_format}",
                        data=export_data,
                        file_name=filename,
                        mime=mime_type,
                        width="stretch",
                    )

                    st.success("✅ Export ready! Click to download your file.")
                else:
                    st.error("No data received from export.")
            else:
                error_msg = (
                    export_result.get("error", "Unknown error")
                    if export_result
                    else "No response from server"
                )
                st.error(f"Export failed: {error_msg}")
    ########################
    with st.expander("Past Sessions", expanded=False, icon="💬"):
        # Use cached session titles from login
        session_title_map = st.session_state.get("cached_session_titles", {})

        if session_title_map:
            session_list = []
            session_ids = []

            search_query = st.session_state.get("session_search", "").lower().strip()
            for session_id, title in reversed(list(session_title_map.items())):
                if session_id and title:
                    if not search_query or search_query in title.lower():
                        session_list.append(title)
                        session_ids.append(session_id)
            if search_query:
                st.info(f"Found {len(session_list)} sessions matching '{search_query}'")
                if not session_list:
                    return

            session_df = pd.DataFrame({"Sessions": session_list})
            session_df.index = session_ids
            dataframe_key = (
                f"cell_table_{st.session_state.get('dataframe_key_counter', 0)}"
            )

            event = st.dataframe(
                session_df.style.hide(axis=0),
                selection_mode="single-cell",
                column_config={"Sessions": st.column_config.TextColumn(width="medium")},
                hide_index=True,
                on_select="rerun",
                key=dataframe_key,
                width="stretch",
            )

            if event and event.selection.cells:
                selected = event.selection.cells[0]
                row_idx, col_label = selected

                if row_idx < len(session_ids):
                    selected_session_id = session_ids[row_idx]
                    selected_title = session_list[row_idx]

                    # The ONLY job of the sidebar is to set this signal.
                    # chat.py (the controller) will handle it.
                    st.session_state["open_session_in_new_tab"] = {
                        "session_id": selected_session_id,
                        "title": selected_title,
                    }
                else:
                    st.error("Invalid session selection. Please try again.")
        else:
            st.info("No sessions found for this user.")


def render_session_sidebar(user_id: str = "user_alpha") -> None:
    """
    Public entrypoint used by chat.py. Builds the whole sidebar.
    This function no longer returns anything.
    """
    cfg = st.session_state.get("bot_config")
    _render_logo_header(cfg)
    _render_user_header()
    st.divider()

    _render_past_sessions(user_id)

    _render_about(cfg)
    _render_external_links(cfg)
    _render_faq(cfg)
    _render_disclaimer(cfg)

    # Version footer at the bottom
    _render_version_footer()


def get_mime_type(file_extension: str) -> str:
    """Return MIME type for an extension."""
    mime_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
    }
    return mime_types.get(file_extension, "application/octet-stream")


def export_chat_history(
    user_id,
    period="day",
    export_format="json",
):
    """Export chat history in the specified format."""
    return export_chat_history_endpoint(user_id, period, export_format)
