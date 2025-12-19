import streamlit as st
import html

try:
    from st_copy import copy_button
except ImportError:
    copy_button = None  # Fallback if package not installed

try:
    from frontend.settings import settings
except Exception:
    from settings import settings
from apis_calls.chat_apis import fetch_llm_result
from apis_calls.session_apis import (
    add_message_to_session,
    update_message_feedback,
    get_image,
)
from navigation.pdf_viewer import display_citations_with_viewer
from manager.tab_manager import update_tab_title
from components.session_sidebar import refresh_session_titles

Bot_ID = settings.bot_id
BACKEND_API_BASE_URL = settings.backend_base_url


def _get_avatars():
    """Return (user_avatar, bot_avatar) from session branding bytes or emoji fallbacks."""
    branding = st.session_state.get("branding_bytes", {})
    user_avatar = branding.get("user_icon") or "👤"
    bot_avatar = branding.get("bot_icon") or "🤖"
    return user_avatar, bot_avatar


def safe_display_image_thumbnail(image_data, caption="Image", unique_key=""):
    """Display an image as a thumbnail with popover for full size view"""

    # Handle legacy format: simple string (image path)
    if isinstance(image_data, str):
        image_result = get_image(image_data)
        if image_result.get("success"):
            # Show thumbnail
            st.image(image_result["content"], caption=caption, width=150)

            # Add popover for full size view
            with st.popover("🔍 Enlarge"):
                st.image(image_result["content"], caption=caption, width="stretch")
            return True
        else:
            st.error(
                f"❌ Failed to load image: {image_result.get('error', 'Unknown error')}"
            )
            return False

    # Handle ImageGroup objects (both dictionary and object format)
    if (hasattr(image_data, "images") and hasattr(image_data, "title")) or (
        isinstance(image_data, dict)
        and "images" in image_data
        and "title" in image_data
    ):
        # Get title and images list (handle both dict and object format)
        if isinstance(image_data, dict):
            title = image_data.get("title", caption)
            images_list = image_data.get("images", [])
        else:
            title = getattr(image_data, "title", caption)
            images_list = getattr(image_data, "images", [])

        if images_list:
            # Display all images in this group as thumbnails
            for img_idx, img in enumerate(images_list):
                # Handle both dict and object format for ImageData
                if isinstance(img, dict):
                    image_url = img.get("image_data_url")
                    page = img.get("page", "")
                elif hasattr(img, "image_data_url"):
                    image_url = getattr(img, "image_data_url")
                    page = getattr(img, "page", "")
                else:
                    continue

                img_caption = (
                    f"{title} - Page {page}"
                    if page
                    else f"{title} - Image {img_idx + 1}"
                )

                if image_url and image_url != "#":
                    image_result = get_image(image_url)
                    if image_result.get("success"):
                        # Show thumbnail
                        st.image(
                            image_result["content"], caption=img_caption, width=150
                        )

                        # Add popover for full size view
                        with st.popover("🔍 Enlarge"):
                            st.image(
                                image_result["content"],
                                caption=img_caption,
                                width="stretch",
                            )
                    else:
                        st.error(
                            f"❌ Failed to load image: {image_result.get('error', 'Unknown error')}"
                        )
            return True
        else:
            st.write(f"📷 No images found in group: {title}")
            return False
    else:
        st.write("📷 Unsupported image format")
        return False


def display_images_container(images, message_id=""):
    """Display all images in a single collapsible container with thumbnails"""
    if not images:
        return

    total_image_count = 0
    # Count total images across all image groups
    for image_data in images:
        if isinstance(image_data, str):
            total_image_count += 1
        elif (hasattr(image_data, "images") and hasattr(image_data, "title")) or (
            isinstance(image_data, dict)
            and "images" in image_data
            and "title" in image_data
        ):
            if isinstance(image_data, dict):
                images_list = image_data.get("images", [])
            else:
                images_list = getattr(image_data, "images", [])
            total_image_count += len(images_list)
        else:
            total_image_count += 1

    # Create single expander for all images
    with st.expander(
        f"📷 Images ({total_image_count} image{'s' if total_image_count != 1 else ''})",
        expanded=False,
    ):
        # Create columns for thumbnail layout
        cols = st.columns(min(total_image_count, 3))  # Max 3 columns
        col_idx = 0

        for idx, image_data in enumerate(images):
            with cols[col_idx % 3]:
                safe_display_image_thumbnail(
                    image_data, f"Image {idx + 1}", f"{message_id}_{idx}"
                )
                col_idx += 1


def render_main_content(user_id: str, active_tab: dict):
    """
    Renders the entire main UI, including the tab bar,
    chat messages, and chat input.
    """
    if not active_tab:
        st.info("Please open a chat from the sidebar.")
        return

    # --- Render Tab Bar (Segmented Control) ---
    tab_labels = []
    tab_options = []
    for i, tab in enumerate(st.session_state["open_tabs"]):
        title = tab["title"]
        if len(title) > 15:
            title = title[:12] + "..."
        tab_labels.append(title)
        tab_options.append(i)  # Use index as option value

    # Ensure active tab index is valid
    current_active_index = active_tab["index"]
    if current_active_index >= len(tab_options):
        current_active_index = max(0, len(tab_options) - 1)
        st.session_state["active_tab_index"] = current_active_index

    tab_config_key = f"tab_selector_{len(st.session_state['open_tabs'])}_{hash(str([tab['session_id'] for tab in st.session_state['open_tabs']]))}"

    st.session_state.setdefault(tab_config_key, current_active_index)

    def on_tab_change():
        """Handle tab selection changes"""
        selected_index = st.session_state.get(tab_config_key)
        if selected_index is None:
            st.session_state[tab_config_key] = current_active_index
            return
        if not (0 <= int(selected_index) < len(tab_options)):
            st.session_state[tab_config_key] = current_active_index
            return
        st.session_state["active_tab_index"] = int(selected_index)

    st.segmented_control(
        "Open Sessions",
        options=tab_options,
        format_func=lambda i: tab_labels[i],
        key=tab_config_key,
        selection_mode="single",
        on_change=on_tab_change,
    )

    # Use the current active index as the effective tab
    effective_tab_index = current_active_index

    # Get current active tab data based on effective selection
    current_tab = st.session_state["open_tabs"][effective_tab_index]
    session_id = current_tab["session_id"]

    # Get messages for this tab (needed for share button check)
    messages = st.session_state["tab_messages"].get(session_id, [])

    # --- Render Tab Header (Title + Action Buttons) ---
    # Use smaller column widths for buttons, title in the middle
    col1, col2, col3 = st.columns([1, 10, 1])

    with col1:
        if st.button(
            "",
            key=f"close_tab_{session_id}",
            type="secondary",
            help="Close Tab",
            icon="❌",
            width="content",
        ):
            st.session_state["tab_to_close"] = effective_tab_index
            st.rerun()

    with col2:
        title_text = html.escape(current_tab["title"])
        st.markdown(
            f'<p style="font-weight: normal; font-size: 20px; margin: 0; padding-top: 0.3em;">{title_text}</p>',
            unsafe_allow_html=True,
        )

    with col3:
        if st.button(
            "",
            key=f"share_tab_{session_id}",
            type="secondary",
            help="Share Session",
            icon="🔗",
            width="content",
        ):
            from apis_calls.session_apis import create_session_share

            # Check if session has messages (can't share empty session)
            if not messages:
                st.warning("⚠️ Cannot share an empty session. Send a message first.")
            else:
                result = create_session_share(session_id, expires_in_days=30)
                if result.get("success"):
                    # Build frontend URL with session_id parameter
                    # Get frontend URL from environment or use default
                    frontend_url = settings.frontend_base_url.rstrip("/")
                    # Use session_id directly in URL (backend checks if session is public)
                    full_share_url = f"{frontend_url}/?session_id={session_id}"
                    # Store in session state for display
                    st.session_state[f"share_url_{session_id}"] = full_share_url
                    st.session_state[f"share_created_{session_id}"] = True
                    st.success("✅ Share link created!")
                    st.rerun()

    # Display share link if available
    if st.session_state.get(f"share_created_{session_id}", False):
        share_url = st.session_state.get(f"share_url_{session_id}", "")
        if share_url:
            st.code(share_url, language=None)

    with st.container(height=700, border=True):
        user_avatar, bot_avatar = _get_avatars()
        # Display chat messages
        for msg_idx, message in enumerate(messages):
            with st.chat_message("user", avatar=user_avatar):
                st.write(message.get("query", ""))

            with st.chat_message("assistant", avatar=bot_avatar):
                st.write(message.get("response", ""))

                citations = message.get("citations", [])
                if citations:
                    display_citations_with_viewer(
                        citations,
                        message_id=f"{session_id}_{message.get('id')}_{msg_idx}",
                    )

                images = message.get("images", [])
                if images:
                    st.write("**Images:**")
                    display_images_container(images)

                # --- START OF FEEDBACK LOGIC ---

                # Render feedback and copy button in a horizontal layout
                feedback_key = f"feedback_{session_id}_{message.get('id')}_{msg_idx}"
                response_text = message.get("response", "")

                # 1. Retrieve existing feedback from the database/message object
                existing_feedback = message.get("feedback")

                # 2. Initialize widget state from database if not exists
                # We must map Backend values to Streamlit values BEFORE the widget renders
                # Backend:  1 (Pos), -1 (Neg), 0 (None/No feedback)
                # Streamlit: 1 (Pos),  0 (Neg), None (No selection)
                if feedback_key not in st.session_state:
                    if existing_feedback == 1:
                        st.session_state[feedback_key] = 1
                    elif existing_feedback == -1:
                        st.session_state[feedback_key] = 0
                    # If existing_feedback is 0 or None, leave widget state unset (None)

                # Create columns for feedback and copy button
                feedback_col, copy_col = st.columns([1, 0.1])

                with feedback_col:
                    # 3. Render the widget
                    # This returns 1 (thumbs up), 0 (thumbs down), or None (no selection)
                    ui_feedback = st.feedback("thumbs", key=feedback_key, width=500)

                with copy_col:
                    if copy_button:
                        copy_button(response_text)
                    else:
                        st.caption("Install st-copy")

                # 4. Handle feedback changes
                # Convert Streamlit value to API value
                if ui_feedback == 0:
                    api_feedback = -1  # Thumbs down
                elif ui_feedback == 1:
                    api_feedback = 1  # Thumbs up
                else:
                    api_feedback = None  # No selection

                # Determine if we need to update the database
                # Case 1: Widget shows a selection (not None)
                if ui_feedback is not None:
                    # Check if this matches what's already in the database
                    if api_feedback == existing_feedback:
                        # State is stable (Widget matches DB) - Do nothing
                        pass
                    else:
                        # User selected a different feedback -> Update
                        result = update_message_feedback(
                            user_id=user_id,
                            session_id=session_id,
                            message_id=message.get("id"),
                            feedback=api_feedback,
                        )

                        if result.get("success"):
                            message["feedback"] = api_feedback
                            st.toast("✅ Feedback updated!")
                        else:
                            st.error(
                                f"❌ Failed to record feedback: {result.get('message', 'Please try again.')}"
                            )
                # Case 2: Widget shows no selection (None) but database has feedback
                # This happens when user clicks to deselect (widget toggles off)
                elif (
                    ui_feedback is None
                    and existing_feedback != 0
                    and existing_feedback is not None
                ):
                    # User deselected -> Clear feedback in database
                    result = update_message_feedback(
                        user_id=user_id,
                        session_id=session_id,
                        message_id=message.get("id"),
                        feedback=0,  # Clear feedback
                    )

                    if result.get("success"):
                        message["feedback"] = 0
                        # Clear the widget state so it stays cleared
                        if feedback_key in st.session_state:
                            del st.session_state[feedback_key]
                        st.toast("✅ Feedback cleared!")
                        st.rerun()
                    else:
                        st.error(
                            f"❌ Failed to clear feedback: {result.get('message', 'Please try again.')}"
                        )

        # Only show welcome message if this is truly a new/empty session
        if not messages:
            # Display welcome message from bot config
            bot_config = st.session_state.get("bot_config", {})
            welcome_message = bot_config.get(
                "welcome_message", "💬 Start a conversation by typing below!"
            )

            with st.chat_message("assistant", avatar=bot_avatar):
                st.write(welcome_message)

        # --- Render Chat Input ---
        chat_input_key = f"chat_input_{session_id}"
        prompt = st.chat_input("Ask anything...", key=chat_input_key)

        flag_key = f"faq_just_clicked_{session_id}"
        if st.session_state.get(flag_key, False):
            st.session_state[flag_key] = False  # Clear flag and stop
        elif prompt and prompt.strip() == "":
            st.warning("⚠️ Please enter a valid message.")
        elif prompt and prompt.strip():
            st.session_state["active_tab_index"] = effective_tab_index
            is_new_session = len(messages) == 0

            if is_new_session:
                words = prompt.split()[:3]
                title = " ".join(words) + ("..." if len(prompt.split()) > 3 else "")
                update_tab_title(effective_tab_index, title)

            with st.chat_message("user", avatar=user_avatar):
                st.write(prompt)

            with st.chat_message("assistant", avatar=bot_avatar):
                response = fetch_llm_result(prompt, sessionID=session_id)

                if isinstance(response, tuple) and len(response) == 2:
                    payload, message_id = response
                else:
                    payload, message_id = response, None

                citations = []
                images = []
                response_text = ""

                if isinstance(payload, dict):
                    # Try to get data from the nested structure first (BotResponse format)
                    data = payload.get(
                        "data", payload
                    )  # Fallback to payload itself if no 'data' key

                    response_text = (
                        data.get("markdown") or payload.get("markdown") or str(payload)
                    )

                    # Try to get references/citations from multiple locations
                    citations = (
                        data.get("references")
                        or payload.get("references")
                        or data.get("citations")
                        or payload.get("citations")
                        or []
                    )

                    images = data.get("images") or payload.get("images") or []

                else:
                    response_text = str(payload)

                st.write(response_text)

                if citations:
                    display_citations_with_viewer(
                        citations, message_id=message_id or f"{session_id}_new"
                    )

                if images:
                    st.write("**Images:**")
                    cols = st.columns(min(len(images), 3))
                    for idx, image_data in enumerate(images):
                        with cols[idx % 3]:
                            safe_display_image_thumbnail(image_data, f"Image {idx + 1}")

            # Persist the message
            new_message = add_message_to_session(
                user_id=user_id,
                session_id=session_id,
                query=prompt,
                response=response_text,
                message_id=message_id,
                bot_id=Bot_ID,
                feedback=None,
                citations=citations,
                images=images,
            )

            if session_id not in st.session_state["tab_messages"]:
                st.session_state["tab_messages"][session_id] = []
            st.session_state["tab_messages"][session_id].append(new_message)

            # Refresh session titles after first response in a new session
            if is_new_session:
                try:
                    refresh_session_titles()
                except Exception:
                    pass  # Don't break the flow if refresh fails

            st.rerun()
