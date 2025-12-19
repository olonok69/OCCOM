import streamlit as st
import os
from apis_calls.superadmin_apis import (
    update_bot_config,
    factory_reset,
    get_bot_config,
    save_image_to_storage,
)
from utils import generate_streamlit_config
import time


def app():
    st.title("Bot Configuration")

    st.markdown(
        """
    <style>
    textarea, input[type="text"] {
        border: 1px solid gray !important;
        border-radius: 4px;
        padding: 8px;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    cfg = st.session_state["bot_config"] or {}

    # General Settings Form
    with st.form("config_form"):
        bot_name = st.text_input("Bot name", cfg.get("bot_name", ""))
        version = st.text_input("Version", cfg.get("version", ""))
        language = st.text_input("Language", cfg.get("language", ""))

        st.markdown("#### Color Settings")
        col1, col2 = st.columns(2)
        with col1:
            primary_color = st.color_picker(
                "Primary color", cfg.get("primary_color", "#D3D3D3")
            )
        with col2:
            secondary_background_color = st.color_picker(
                "Secondary Background Color",
                cfg.get("secondary_background_color", "#F0F2F6"),
            )

        col3, col4 = st.columns(2)
        with col3:
            background_color = st.color_picker(
                "Background Color",
                cfg.get("background_color", "#FFFFFF"),
            )
        with col4:
            text_color = st.color_picker("Text Color", cfg.get("text_color", "#262730"))

        about_text = st.text_area("About", cfg.get("about_text", ""))

        disclaimer_text = st.text_area("Disclaimer", cfg.get("disclaimer_text", ""))
        
        # --- External Links (up to 3) ---
        st.markdown("#### External Links (Max 3)")
        current_links = cfg.get("external_links", [])
        # Ensure we have a list of exactly 3 items to iterate comfortably, filling defaults
        # We only persist them if both title/url are non-empty.
        padded_links = current_links + [{"title": "", "url": ""}] * (3 - len(current_links))
        padded_links = padded_links[:3]  # hard limit 3

        collected_links = []
        for i, link_obj in enumerate(padded_links):
            c_link1, c_link2 = st.columns([1, 2])
            with c_link1:
                l_title = st.text_input(f"Link {i+1} Title", link_obj.get("title", ""), key=f"link_title_{i}")
            with c_link2:
                l_url = st.text_input(f"Link {i+1} URL", link_obj.get("url", ""), key=f"link_url_{i}")
            
            collected_links.append({"title": l_title.strip(), "url": l_url.strip()})
        
        contact_email = st.text_input(
            "Contact email", cfg.get("feedback_contact_email", "")
        )
        contact_name = st.text_input(
            "Contact name", cfg.get("feedback_contact_name", "")
        )

        faqs_text = st.text_area("FAQs (one per line)", "\n".join(cfg.get("faq", [])))
        system_prompt = st.text_area("System Prompt", cfg.get("system_prompt", ""))
        st.caption(
            "System prompt should always have {{today_date}}, {{formatted_documents}}, {{context_str}}, and {{question}} placeholders. "
        )

        # --- Filters: count & names (no realtime, saved on submit) ---
        st.markdown("#### Filters")
        has_filters_val = st.toggle(
            "Enable filters",
            value=bool(cfg.get("has_filters", False)),
            help="Turn on to enable filters. This only saves a boolean flag for now.",
        )

        # current filters as default
        existing_filters = cfg.get("filters", {})
        if isinstance(existing_filters, dict):
            existing_filter_names = list(existing_filters.values())
        elif isinstance(existing_filters, list):
            existing_filter_names = [str(x) for x in existing_filters]
        else:
            existing_filter_names = []

        num_filters = st.number_input(
            "Number of filters",
            min_value=0,
            max_value=50,
            value=len(existing_filter_names),
            step=1,
            help="How many filters to expose.",
        )

        filter_names = []
        st.markdown("Filter Names:")
        for i in range(int(num_filters)):
            default_name = (
                existing_filter_names[i] if i < len(existing_filter_names) else ""
            )
            name = st.text_input(
                f"Filter {i + 1}", value=default_name, key=f"filter_name_{i}"
            ).strip()
            if name:
                filter_names.append(name)

        # --- Sub-categories (2-level only) -----------------------------------------
        st.markdown("#### Sub-categories")
        st.caption("Choose Sub-categories. Maximum depth is 2.")

        # 1) Render multi-selects for each parent candidate (every filter name is a parent candidate)
        raw_children_choices = {}  # { parent_name: [child_name, ...] }
        for parent in filter_names:
            # A parent cannot list itself as a child
            options = [n for n in filter_names if n != parent]

            chosen = st.multiselect(
                f"Sub-category of '{parent}'",
                options=options,
                default=[],
                key=f"sub_of_{parent}",
            )
            raw_children_choices[parent] = chosen

        # 2) Build a *cleaned* mapping that enforces the constraints below:
        #    - Max depth = 2 (a node cannot be both parent and child simultaneously)
        #    - A child can only belong to ONE parent
        #    - No cycles / no multi-level chains

        # --- Validate + build mapping (no helper; enforce: no circular, max depth=2) ---

        # Validate circular / depth > 2
        hierarchy_errors = []
        for p, childs in (raw_children_choices or {}).items():
            for c in childs or []:
                if c == p:
                    hierarchy_errors.append(f"'{p}' cannot be its own child.")
                    continue
                c_children = raw_children_choices.get(c, []) or []
                if p in c_children:
                    # mutual selection A <-> B
                    hierarchy_errors.append(f"Circular relation: '{p}' <-> '{c}'.")
                if len(c_children) > 0:
                    # child has children -> depth would exceed 2
                    hierarchy_errors.append(
                        f"Depth limit exceeded: '{p}' -> '{c}' and '{c}' has its own children."
                    )

        has_hierarchy_error = len(hierarchy_errors) > 0
        if has_hierarchy_error:
            st.warning(
                "⚠️ Invalid hierarchy detected. Please fix the following and try again:"
            )
            for msg in hierarchy_errors:
                st.caption(f"- {msg}")

        # Build final mapping only if no errors
        assigned_children = set()
        final_mapping = {}

        if not has_hierarchy_error:
            # Greedy assign children; skip duplicates and self-assignments
            for p in filter_names:
                if p in assigned_children:
                    continue
                selected = raw_children_choices.get(p, []) or []

                cleaned = []
                for c in selected:
                    if c == p:
                        continue
                    if c not in filter_names:
                        continue
                    if c in assigned_children:
                        continue
                    cleaned.append(c)
                    assigned_children.add(c)

                # Tentatively keep; may be removed if ends up a child of someone
                final_mapping[p] = cleaned

            # Children cannot be parents (strict 2-level)
            for ch in list(assigned_children):
                final_mapping.pop(ch, None)

            # Drop empty parents (no [] entries)
            final_mapping = {k: v for k, v in final_mapping.items() if v}

        # Keep for submit stage
        _mapping_ready = final_mapping
        _hierarchy_error = has_hierarchy_error

        # Center the submit button and make it green
        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            submitted = st.form_submit_button(
                "☑️ Update Config", type="primary", use_container_width=True
            )

        if submitted:
            # --- System Prompt validation ---
            if not system_prompt or system_prompt.strip() == "":
                st.error("❌ System Prompt cannot be empty.")
                st.stop()
            required_variables = {
                "{{today_date}}",
                "{{formatted_documents}}",
                "{{context_str}}",
                "{{question}}",
            }

            missing = [v for v in required_variables if v not in system_prompt]
            if missing:
                st.error(
                    "❌ Missing required placeholders in System Prompt: "
                    + ", ".join(missing)
                )
                st.stop()

            # Build filters dict from names regardless; whether to save depends on toggle
            if bool(has_filters_val):
                filters_dict = {
                    f"filter_{i + 1}": name for i, name in enumerate(filter_names)
                }
            else:
                filters_dict = {}

            # [IMPORTANT] Block save when hierarchy invalid
            if bool(has_filters_val) and _hierarchy_error:
                st.error(
                    "Update failed: Circular relation or more than 2 levels detected. Please fix and try again."
                )

            updates = {
                "has_filters": bool(has_filters_val),
                "filters": filters_dict,
                "filter_mapping": final_mapping,
                "faq": [
                    line.strip() for line in faqs_text.splitlines() if line.strip()
                ],
                "system_prompt": system_prompt,
                "feedback_contact_email": contact_email,
                "feedback_contact_name": contact_name,
                "bot_name": bot_name,
                "version": version,
                "language": language,
                "about_text": about_text,
                "disclaimer_text": disclaimer_text,
                "primary_color": primary_color,
                "secondary_background_color": secondary_background_color,
                "background_color": background_color,
                "text_color": text_color,
                "font_family": "Arial, sans-serif",
                "font_size": "14px",
                "welcome_message": "Hi! How can I assist you today?",
                "default_response": "I'm sorry, I didn't understand that. Could you please rephrase?",
                "external_links": [
                    L for L in collected_links 
                    if L["title"] and L["url"]
                ],
            }

            new_cfg = update_bot_config(updates)
            try:
                st.session_state["bot_config"] = new_cfg
                generate_streamlit_config()
                st.success("✅ Configuration updated.")
                time.sleep(3)
                st.rerun()

            except Exception as e:
                st.error(f"Error generating theme config: {str(e)}")

            st.json(new_cfg)

    st.divider()

    # Image Uploads Section
    st.subheader("Upload Images")

    # Logo Upload
    st.markdown("### Bot Logo")
    logo_file = st.file_uploader(
        "Upload bot logo", type=["png", "jpg", "jpeg"], key="upload_logo"
    )
    if logo_file is not None and st.button("Save Logo", key="save_logo"):
        try:
            st.session_state.setdefault("branding_bytes", {})
            st.session_state["branding_bytes"]["logo"] = logo_file.getvalue()
            res = save_image_to_storage("logo", logo_file)
            if res.get("status") == "success":
                st.success("Logo uploaded.")
                time.sleep(3)
                st.rerun()
            else:
                st.error(f"Upload failed: {res}")
        except Exception as e:
            st.error(f"Failed to save logo: {e}")

    st.divider()

    # Bot Icon Upload
    st.markdown("### Bot Icon")
    bot_icon_file = st.file_uploader(
        "Upload Bot Icon", type=["png", "jpg", "jpeg", "gif"], key="bot_icon_uploader"
    )
    if bot_icon_file is not None and st.button("Save Bot Icon", key="save_bot_icon"):
        try:
            st.session_state.setdefault("branding_bytes", {})
            st.session_state["branding_bytes"]["bot_icon"] = bot_icon_file.getvalue()

            res = save_image_to_storage("bot_icon", bot_icon_file)
            if res.get("status") == "success":
                st.success("Bot icon uploaded.")
                time.sleep(3)
                st.rerun()
            else:
                st.error(f"Upload failed: {res}")
        except Exception as e:
            st.error(f"Error saving bot icon: {e}")

    st.divider()

    # User Icon Upload
    st.markdown("### User Icon")
    user_icon_file = st.file_uploader(
        "Upload User Icon", type=["png", "jpg", "jpeg", "gif"], key="user_icon_uploader"
    )
    if user_icon_file is not None and st.button("Save User Icon", key="save_user_icon"):
        try:
            st.session_state.setdefault("branding_bytes", {})
            st.session_state["branding_bytes"]["user_icon"] = user_icon_file.getvalue()

            res = save_image_to_storage("user_icon", user_icon_file)
            if res.get("status") == "success":
                st.success("User icon uploaded.")
                time.sleep(3)
                st.rerun()
            else:
                st.error(f"Upload failed: {res}")
        except Exception as e:
            st.error(f"Error saving user icon: {e}")

    st.divider()

    # Factory Reset Section - DANGER ZONE
    st.markdown("### 🚨 Danger Zone")
    st.warning(
        "⚠️ **WARNING**: Factory reset will permanently delete ALL uploaded files, "
        "images, search index data, and reset configuration to defaults. "
        "This action CANNOT be undone!"
    )

    # Check if factory reset is enabled via environment variable
    factory_reset_enabled = os.getenv("FACTORY_RESET_BOT", "false").lower() == "true"

    if not factory_reset_enabled:
        st.info(
            "ℹ️ Factory reset is currently disabled. "
            "To enable, set environment variable `FACTORY_RESET_BOT=true` in the backend."
        )

    # Create a checkbox for confirmation
    confirm_reset = st.checkbox(
        "I understand this will delete all data and cannot be undone",
        key="confirm_factory_reset",
    )

    # Factory Reset Button
    if st.button(
        "🗑️ Factory Reset",
        type="primary" if confirm_reset else "secondary",
        disabled=not confirm_reset,
        key="factory_reset_button",
        help="Delete all data and reset to factory defaults",
    ):
        if confirm_reset:
            with st.spinner(
                "⏳ Performing factory reset... This may take a few minutes."
            ):
                try:
                    result = factory_reset()

                    if result.get("success"):
                        st.success("✅ Factory reset completed successfully!")

                        # Show detailed results
                        data = result.get("data", {})
                        results = data.get("results", {})

                        with st.expander("View Reset Details"):
                            st.json(results)

                        # Reload the bot config from backend
                        try:
                            st.info("🔁 Reloading configuration from backend...")
                            new_config = get_bot_config()
                            if new_config:
                                st.session_state["bot_config"] = new_config
                                st.session_state["branding_bytes"]["logo"] = (
                                    new_config.get("images").get("logo_base64")
                                )
                                st.session_state["branding_bytes"]["bot_icon"] = (
                                    new_config.get("images").get("bot_icon_base64")
                                )
                                st.session_state["branding_bytes"]["user_icon"] = (
                                    new_config.get("images").get("user_icon_base64")
                                )
                                st.success("✅ Configuration reloaded successfully!")
                                st.info(
                                    "🔁 Refreshing page to show updated configuration..."
                                )
                                st.rerun()
                            else:
                                st.warning(
                                    "⚠️ Could not reload config automatically. Please refresh the page manually."
                                )
                        except Exception as reload_ex:
                            st.warning(
                                f"⚠️ Could not reload config: {reload_ex}. Please refresh the page manually."
                            )

                    else:
                        error_msg = result.get("error", "Unknown error occurred")
                        st.error(f"❌ Factory reset failed: {error_msg}")

                        if result.get("status_code") == 403:
                            st.info(
                                "💡 Tip: Make sure `FACTORY_RESET_BOT=true` is set in the backend "
                                "environment variables and restart the backend service."
                            )

                except Exception as e:
                    st.error(f"❌ Error during factory reset: {str(e)}")
        else:
            st.warning("⚠️ Please confirm the action by checking the box above.")


app()
