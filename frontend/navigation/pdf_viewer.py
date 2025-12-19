import logging
import streamlit as st
import base64
import requests
from typing import Dict, Any
from urllib.parse import quote
import uuid

STREAM_CHUNK_SIZE = 512 * 1024  # 512 KB chunks keep download memory predictable

try:
    from frontend.settings import settings
except Exception:
    from settings import settings

logger = logging.getLogger(__name__)
FRONT_EXCEPTION_TAG = "FRONT_EXCEPTION"


@st.cache_data(ttl=3600, max_entries=15, show_spinner=False)
def fetch_pdf_bytes(api_url: str, headers: dict):
    """
    Fetch PDF bytes from backend API with caching.

    Returns:
        Tuple of (pdf_bytes, status_code, response_headers)
    """
    try:
        response = requests.get(
            api_url,
            headers=headers,
            timeout=30,
            stream=True,
        )

        headers_snapshot = dict(response.headers)

        if response.status_code == 200:
            buffer = bytearray()
            for chunk in response.iter_content(STREAM_CHUNK_SIZE):
                if chunk:
                    buffer.extend(chunk)
            return bytes(buffer), response.status_code, headers_snapshot

        return None, response.status_code, headers_snapshot
    except requests.exceptions.Timeout as timeout_err:
        logger.warning(
            "%s pdf_viewer.fetch_pdf_bytes_timeout",
            FRONT_EXCEPTION_TAG,
            exc_info=timeout_err,
        )
        return None, 408, {}
    except Exception:
        logger.exception("%s pdf_viewer.fetch_pdf_bytes_failed", FRONT_EXCEPTION_TAG)
        return None, 500, {}


def _render_word_download_popover(
    *,
    label: str,
    citation: dict,
    filename: str,
    clean_filename: str,
    message_id: str,
    citation_index: int,
    help_text: str,
    is_primary_control: bool,
):
    """Render a popover that fetches and downloads the Word source for a citation."""

    popover_suffix = "primary" if is_primary_control else "download"
    popover_key = f"word_popover_{message_id}_{citation_index}_{popover_suffix}"
    download_help = help_text or f"Download Word source for {clean_filename}"

    with st.popover(label, key=popover_key, help=download_help):
        title = citation.get("title", clean_filename)
        st.write(f"**📄 {title}**")

        section_info = []
        section_number = citation.get("section_number")
        chapter = citation.get("chapter")
        page_number = citation.get("page_number")

        if section_number and section_number != "N/A":
            section_info.append(f"Section {section_number}")
        if chapter and chapter != "N/A":
            section_info.append(chapter)
        if page_number:
            section_info.append(f"Page {page_number}")

        if section_info:
            st.caption(" • ".join(section_info))

        if not settings.auth_token:
            st.info("🔒 Sign in to download this document.")
            return

        download_key = f"download_action_{message_id}_{citation_index}"
        if st.button(
            f"💾 Fetch {clean_filename}",
            key=f"download_btn_{download_key}",
            type="primary",
        ):
            try:
                download_url = (
                    f"{settings.backend_base_url}/v1/get-pdf/{quote(filename)}"
                )
                with st.spinner("Fetching file for download..."):
                    response = requests.get(
                        download_url,
                        headers=settings.build_headers(None, None),
                        timeout=30,
                        stream=True,
                    )

                if response.status_code == 200:
                    file_buffer = bytearray()
                    for chunk in response.iter_content(STREAM_CHUNK_SIZE):
                        if chunk:
                            file_buffer.extend(chunk)
                    file_data = bytes(file_buffer)
                    mime = (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        if filename.lower().endswith(".docx")
                        else "application/msword"
                    )
                    st.download_button(
                        label=f"📥 Save {clean_filename}",
                        data=file_data,
                        file_name=clean_filename,
                        mime=mime,
                        key=f"save_{download_key}",
                    )
                    st.success("✅ Click 'Save' to download the file!")
                elif response.status_code in {401, 403}:
                    st.error("❌ Sign in to download this document.")
                elif response.status_code == 404:
                    st.error("❌ File not found in storage.")
                else:
                    st.error(f"❌ Failed to fetch file: {response.status_code}")
            except requests.exceptions.Timeout as timeout_err:
                logger.warning(
                    "%s pdf_viewer.word_download_timeout",
                    FRONT_EXCEPTION_TAG,
                    exc_info=timeout_err,
                )
                st.error("⏱️ Download timed out. Please try again.")
            except Exception as exc:
                logger.exception(
                    "%s pdf_viewer.word_download_failed", FRONT_EXCEPTION_TAG
                )
                st.error(f"❌ Error fetching file: {str(exc)}")


@st.fragment(run_every=None)
def display_citations_with_viewer_fragment(
    citations: list,
    BACKEND_API_BASE_URL: str = "",
    message_id: str = None,
):
    """
    Fragment to display citations as clickable links that open PDF viewer inline with chat.
    This fragment includes both the citation buttons and the PDF viewer.
    Only this fragment will refresh when a citation button is clicked.
    """
    if not citations:
        return

    # Create unique message ID for button keys
    if message_id is None:
        message_id = f"msg_{len(st.session_state.get('chat_messages', []))}"

    # Display compact citation buttons
    st.markdown("**📚 References:**")

    # Display citation buttons in a compact row
    cols = st.columns(len(citations))
    for i, citation in enumerate(citations, 1):
        with cols[i - 1]:
            filename = citation.get("file_name", "")
            is_word_doc = filename.lower().endswith((".docx", ".doc"))
            clean_filename = filename

            # Create unique key by combining message_id and citation number
            unique_key = f"citation_btn_{message_id}_{i}"

            # Build help text with section, chapter, and chunk_type if available
            metadata = citation.get("metadata", {})
            section_number = citation.get("section_number") or metadata.get(
                "section_number", ""
            )
            chapter = citation.get("chapter") or metadata.get("chapter", "")
            chunk_type = citation.get("chunk_type") or metadata.get("chunk_type", "")

            help_text = f"View {citation.get('title', 'Document')} - Page {citation.get('page_number', 1)}"
            if chapter and chapter != "N/A":
                help_text += f" - Chapter: {chapter}"
            if section_number and section_number != "N/A":
                help_text += f" - Section {section_number}"
            if chunk_type and chunk_type != "N/A":
                help_text += f" ({chunk_type})"

            # Check if there's a PDF version of a Word document
            display_as_pdf = False
            display_filename = filename

            if is_word_doc:
                base_name = filename.rsplit(".", 1)[0]
                pdf_filename = f"{base_name}.pdf"

                try:
                    check_url = (
                        f"{settings.backend_base_url}/v1/get-pdf/{quote(pdf_filename)}"
                    )
                    pdf_bytes, status_code, _ = fetch_pdf_bytes(
                        check_url, settings.build_headers(None, None)
                    )

                    if status_code == 200 and pdf_bytes:
                        display_as_pdf = True
                        display_filename = pdf_filename
                except Exception:
                    pass

            if is_word_doc and not display_as_pdf:
                _render_word_download_popover(
                    label=f"[{i}]",
                    citation=citation,
                    filename=filename,
                    clean_filename=clean_filename,
                    message_id=message_id,
                    citation_index=i,
                    help_text=help_text,
                    is_primary_control=True,
                )
                continue

            # PDF documents or Word documents with PDF versions - show numbered button and inline viewer
            if st.button(
                f"[{i}]",
                key=unique_key,
                help=help_text,
            ):
                st.session_state.inline_pdf_to_display = {
                    "filename": display_filename,
                    "page_number": int(citation.get("page_number", 1)),
                    "BACKEND_API_BASE_URL": settings.backend_base_url,
                    "message_id": message_id,
                    "citation_index": i - 1,
                    "citations": citations,
                    "doc_id": citation.get("doc_id"),
                }

            if is_word_doc:
                _render_word_download_popover(
                    label=f"⬇️{i}",
                    citation=citation,
                    filename=filename,
                    clean_filename=clean_filename,
                    message_id=message_id,
                    citation_index=i,
                    help_text=f"Download Word source for {clean_filename}",
                    is_primary_control=False,
                )

    # Display PDF viewer inline if there's a PDF to display for this message
    if "inline_pdf_to_display" in st.session_state:
        pdf_info = st.session_state.inline_pdf_to_display
        # Only show PDF if it's for this message
        if pdf_info.get("message_id") == message_id:
            _display_pdf_inline(pdf_info, settings.backend_base_url)


def display_citations_with_viewer(
    citations: list,
    BACKEND_API_BASE_URL: str = "",
    message_id: str = None,
):
    """
    Display citations as clickable links that open PDF viewer inline with chat.
    This is the main function to use in the chat interface.
    Wrapper function that calls the fragment version.
    """
    display_citations_with_viewer_fragment(citations, BACKEND_API_BASE_URL, message_id)


def _display_pdf_inline(pdf_info: dict, BACKEND_API_BASE_URL: str):
    """
    Helper function to display PDF inline. Used within fragments.
    """
    filename = pdf_info["filename"]
    page_number = pdf_info["page_number"]
    message_id = pdf_info["message_id"]
    citations = pdf_info.get("citations", [])

    # Add close button and citation switcher
    col1, col2, col3 = st.columns([1, 8, 1])

    with col1:
        if st.button("✕", key=f"close_inline_pdf_{message_id}", help="Close PDF"):
            st.session_state.pop("inline_pdf_to_display", None)  # Safe removal
            st.rerun()  # Force immediate refresh
            # Fragment will automatically rerun on button click

    with col2:
        st.markdown(f"**📄 {filename} - Page {page_number}**")

    with col3:
        # Show current citation info if multiple citations available
        if citations and len(citations) > 1:
            current_index = next(
                (i for i, c in enumerate(citations) if c.get("file_name") == filename),
                0,
            )
            st.markdown(f"**{current_index + 1}/{len(citations)}**")

    # Display PDF inline
    try:
        # Use filename to fetch the PDF from blob storage
        api_url = f"{settings.backend_base_url}/v1/get-pdf/{quote(filename)}"
        st.caption(f"🔍 Fetching: {filename}")

        # Fetch PDF with caching (Streamlit automatically caches based on function parameters)
        pdf_bytes, status_code, response_headers = fetch_pdf_bytes(
            api_url, settings.build_headers(None, None)
        )

        if status_code == 200 and pdf_bytes:
            # Encode PDF to base64
            pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

            iframe_url = (
                "data:application/pdf;base64,"
                + pdf_base64
                + "#page="
                + str(page_number)
            )
            # save the file to a temporary file to serve in the iframe if file is larger than 2mb
            content_length = response_headers.get("Content-Length")
            try:
                content_length_int = int(content_length) if content_length else None
            except ValueError:
                content_length_int = None

            inline_threshold = 2 * 1024 * 1024
            effective_size = content_length_int or len(pdf_bytes)

            if effective_size > inline_threshold:
                temp_file_name = uuid.uuid4().hex + ".pdf"
                with open("static/" + temp_file_name, "wb") as f:
                    f.write(pdf_bytes)
                iframe_url = (
                    settings.frontend_base_url
                    + "/app/static/"
                    + temp_file_name
                    + "#page="
                    + str(page_number)
                )

            iframe_html = f"""
            <iframe 
                src="{iframe_url}" 
                width="100%" 
                height="1000px" 
                style="border: none;">
                <p>Your browser does not support PDFs. 
                    <a href="{iframe_url}">Download the PDF</a>
                </p>
            </iframe>
            """
            # Display using Streamlit's HTML component
            st.markdown(iframe_html, unsafe_allow_html=True)

        elif status_code == 404:
            st.error(
                "❌ File not found. Please check if the file has been processed and indexed."
            )

        elif status_code == 403:
            st.error("❌ Access denied. You don't have permission to view this file.")

        elif status_code == 400:
            st.error("❌ Invalid filename. Please check the filename format.")

        else:
            st.error(f"❌ Error from backend: Status {status_code}")

    except requests.exceptions.ConnectionError as conn_err:
        logger.warning(
            "%s pdf_viewer.connection_error", FRONT_EXCEPTION_TAG, exc_info=conn_err
        )
        st.error(
            "❌ Cannot connect to the backend server. Please make sure the backend is running."
        )

    except requests.exceptions.Timeout as timeout_err:
        logger.warning(
            "%s pdf_viewer.timeout", FRONT_EXCEPTION_TAG, exc_info=timeout_err
        )
        st.error("⏱️ The request timed out. Please try again.")

    except Exception as e:
        logger.exception("%s pdf_viewer.inline_view_failed", FRONT_EXCEPTION_TAG)
        st.error(f"❌ An unexpected error occurred: {str(e)}")


@st.fragment(run_every=None)
def display_inline_pdf_fragment():
    """
    Fragment to display PDF inline below the citations in the chat.
    Only this fragment will refresh when opening/closing PDFs.
    """
    # Check if there's a PDF to display
    if "inline_pdf_to_display" not in st.session_state:
        return

    pdf_info = st.session_state.inline_pdf_to_display
    _display_pdf_inline(pdf_info, settings.backend_base_url)


def display_inline_pdf(pdf_info: dict):
    """
    Display PDF inline below the citations in the chat.
    Wrapper function that calls the fragment version.
    """
    # Store pdf_info in session state if not already there
    if "inline_pdf_to_display" not in st.session_state:
        st.session_state.inline_pdf_to_display = pdf_info

    # Call the fragment
    display_inline_pdf_fragment()


def show_citation_metadata(citation: Dict[str, Any]):
    """
    Display detailed metadata for a citation.
    """
    metadata = citation.get("metadata", {})

    if not metadata:
        st.info("No additional metadata available")
        return

    st.markdown("### 📊 Document Metadata")

    # Display metadata in a structured way
    col1, col2 = st.columns(2)

    with col1:
        if metadata.get("report_name"):
            st.markdown(f"**Report Name:** {metadata['report_name']}")
        if metadata.get("publisher"):
            st.markdown(f"**Publisher:** {metadata['publisher']}")
        if metadata.get("category"):
            st.markdown(f"**Category:** {metadata['category']}")
        if metadata.get("publishing_year"):
            st.markdown(f"**Publishing Year:** {metadata['publishing_year']}")

    with col2:
        if metadata.get("geographical_area"):
            st.markdown(f"**Geographical Area:** {metadata['geographical_area']}")
        if metadata.get("access_level"):
            st.markdown(f"**Access Level:** {metadata['access_level']}")
        if metadata.get("language"):
            st.markdown(f"**Language:** {metadata['language']}")
        if metadata.get("period_covered"):
            st.markdown(f"**Period Covered:** {metadata['period_covered']}")
        if metadata.get("section_number") or citation.get("section_number"):
            section = metadata.get("section_number") or citation.get("section_number")
            st.markdown(f"**Section:** {section}")
        if metadata.get("chapter") or citation.get("chapter"):
            chapter = metadata.get("chapter") or citation.get("chapter")
            st.markdown(f"**Chapter:** {chapter}")
        if metadata.get("chunk_type") or citation.get("chunk_type"):
            chunk_type = metadata.get("chunk_type") or citation.get("chunk_type")
            st.markdown(f"**Chunk Type:** {chunk_type}")

    # Show content indicators
    st.markdown("### 📋 Content Indicators")
    col1, col2, col3 = st.columns(3)

    with col1:
        if metadata.get("images"):
            st.markdown(f"🖼️ **Images:** {len(metadata['images'])} found")
        else:
            st.markdown("🖼️ **Images:** None")

    with col2:
        if metadata.get("charts"):
            st.markdown(f"📊 **Charts:** {len(metadata['charts'])} found")
        else:
            st.markdown("📊 **Charts:** None")

    with col3:
        if metadata.get("tables"):
            st.markdown(f"📋 **Tables:** {len(metadata['tables'])} found")
        else:
            st.markdown("📋 **Tables:** None")
