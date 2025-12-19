import logging
import os
from typing import Callable

from dotenv import load_dotenv
import streamlit as st

try:
    from settings import settings
except ImportError:
    from frontend.settings import settings


# from dotenv import load_dotenv only locally
# load_dotenv()
TELEMETRY_CONFIGURED = os.getenv("TELEMETRY_CONFIGURED", "false").lower() == "true"
try:
    # Simple, test-validated configuration for Azure Monitor
    from azure.monitor.opentelemetry import configure_azure_monitor

    TELEMETRY_CONFIGURED = False
    _AZ_MONITOR_FLAG = os.environ.get("AZURE_MONITOR_CONFIGURED") == "1"
    conn_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")

    if conn_string and not _AZ_MONITOR_FLAG:
        configure_azure_monitor(connection_string=conn_string)
        os.environ["AZURE_MONITOR_CONFIGURED"] = "1"
        TELEMETRY_CONFIGURED = True
    elif conn_string and _AZ_MONITOR_FLAG:
        TELEMETRY_CONFIGURED = True
except ImportError:
    TELEMETRY_CONFIGURED = False


logger = logging.getLogger("frontend")
FRONT_EXCEPTION_TAG = "FRONT_EXCEPTION"

_log_level_name = os.getenv("LOG_LEVEL", "DEBUG").upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
logger.setLevel(_log_level)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(_log_level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    logger.addHandler(handler)

_frontend_log_level = _log_level

logging.getLogger("streamlit").setLevel(_frontend_log_level)
logging.getLogger("frontend").setLevel(_frontend_log_level)
logging.getLogger("uvicorn").setLevel(_frontend_log_level)

logging.getLogger("opentelemetry").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)


def _stringify_message(message: object) -> str:
    """Best-effort conversion of Streamlit message bodies to strings for logging."""

    if isinstance(message, BaseException):
        return f"{message.__class__.__name__}: {message}"

    try:
        return str(message)
    except Exception:  # pragma: no cover - defensive conversion
        return "Streamlit message emitted, but body could not be stringified"


def _wrap_streamlit_message(
    func_name: str, log_callable: Callable[[str], None]
) -> None:
    flag_name = f"_{func_name}_logging_wrapped"
    if getattr(st, flag_name, False):
        return

    original_fn = getattr(st, func_name)

    def _logged_streamlit_fn(body, *args, **kwargs):
        log_message = _stringify_message(body)
        log_callable(log_message)
        return original_fn(body, *args, **kwargs)

    setattr(st, func_name, _logged_streamlit_fn)
    setattr(st, flag_name, True)


_wrap_streamlit_message("error", logger.error)
_wrap_streamlit_message("warning", logger.warning)
_wrap_streamlit_message("info", logger.info)

logger.info("FrontEnd telemetry configured: %s", TELEMETRY_CONFIGURED)

# Add global CSS to make feedback buttons horizontal and hide header anchor links
st.markdown(
    """
    <style>
    /* Force feedback buttons to display horizontally */
    div[data-testid="stFeedback"] {
        display: flex !important;
        flex-direction: row !important;
        gap: 8px !important;
        align-items: center !important;
    }
    div[data-testid="stFeedback"] > div {
        display: inline-flex !important;
    }
    
    /* Hide anchor link icons on all headers */
    h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {
        display: none !important;
    }
    /* Hide anchor links in Streamlit title, header, and subheader elements */
    [data-testid="stHeader"] a,
    [data-testid="stSubheader"] a,
    .stMarkdown h1 a,
    .stMarkdown h2 a,
    .stMarkdown h3 a,
    .stMarkdown h4 a,
    .stMarkdown h5 a,
    .stMarkdown h6 a {
        display: none !important;
    }
    /* Hide anchor icons that appear on hover */
    h1:hover a, h2:hover a, h3:hover a, h4:hover a, h5:hover a, h6:hover a {
        display: none !important;
    }

    /* Global: normalize main content padding across pages */
    [data-testid="block-container"] {
        padding: 2rem !important;
    }
    /* Extra override for current Emotion class if present */
    .st-emotion-cache-c38l67 {
        padding: 2rem !important;
    }
    
    </style>
""",
    unsafe_allow_html=True,
)

# Conditionally hide sidebar on login page
if not st.session_state.get("is_authenticated", False):
    st.markdown(
        """
        <style>
        /* Hide sidebar when not authenticated (login page) */
        [data-testid="stSidebar"] {
            display: none !important;
        }
        /* Hide sidebar toggle button when not authenticated */
        button[data-testid="baseButton-header"] {
            display: none !important;
        }
        /* Adjust main content to full width when sidebar is hidden */
        .main .block-container {
            max-width: 100% !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
        /* Hide the deploy button */
    .stAppDeployButton {
        display: none !important;
    }
    /* Hide the main menu */
    .stMainMenu {
        display: none !important;
    }
    </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    def logout():
        # Clear all session state but preserve bot_id from environment
        st.session_state.clear()
        # Immediately set bot_id from environment after clearing
        st.session_state["bot_id"] = settings.bot_id

    st.session_state.setdefault("page", "home")

    # Check if this is a shared session request (public access, no auth)
    # Must check query params FIRST, before any navigation setup
    session_id = None
    try:
        query_params = st.query_params
        if query_params:
            session_id = query_params.get("session_id")
    except Exception:
        logger.exception("%s session_query_params", FRONT_EXCEPTION_TAG)

    if session_id:
        # Public shared session page - no authentication required
        # IMPORTANT: Preserve id_token if it exists - never overwrite it
        # Session is marked as public on backend, so we can access it directly
        st.session_state["is_shared_session"] = True
        st.session_state["is_authenticated"] = True  # Temporarily bypass auth
        st.session_state["shared_session_id"] = (
            session_id  # Store session_id for the page
        )
        # id_token is NOT touched - it remains unchanged if it exists
        shared_page = st.Page(
            "navigation/shared_session.py", title="Shared Session", icon="📤"
        )
        pg = st.navigation([shared_page])
        pg.run()
        return

    # Normal authentication flow
    # st.session_state.setdefault("is_authenticated", False)

    login = st.Page("navigation/loginpage.py", title="Login", icon="🔒")
    if not st.session_state.get("is_authenticated", False):
        st.session_state["is_authenticated"] = False
    if st.session_state["is_authenticated"] is not True:
        pg = st.navigation([login])

        pg.run()
        logger.info("User not authenticated, showing login page.")

    else:
        if settings.is_debug:
            # Optional debug role switchers
            with st.container(horizontal=True):
                st.button(
                    "Change role to super-admin",
                    on_click=lambda: st.session_state.update({"role": "super-admin"}),
                )

                st.button(
                    "Change role to admin",
                    on_click=lambda: st.session_state.update({"role": "admin"}),
                )

                st.button(
                    "Change role to user",
                    on_click=lambda: st.session_state.update({"role": "user"}),
                )
        chat = st.Page("navigation/chat.py", title="Chat", icon="💬")

        upload = st.Page("navigation/uploads.py", title="Upload Page", icon="📤")

        fileviewer = st.Page("navigation/fileviewer.py", title="File Viewer", icon="📁")

        stats = st.Page("navigation/stats.py", title="Statistics", icon="📊")
        if settings.is_show_auth_token:
            with st.expander("Debug Info"):
                st.write(f"token: {settings.auth_token}")
        config = st.Page("navigation/config.py", title="Configuration", icon="⚙️")
        if st.session_state["role"] == "super-admin":
            pg = st.navigation(
                {
                    "Chat": [chat],
                    "Admin": [upload, fileviewer, stats],
                    "Super Admin": [config],
                },
                position="top",
            )

        elif st.session_state["role"] == "admin":
            pg = st.navigation(
                {"Chat": [chat], "Admin": [upload, fileviewer, stats]}, position="top"
            )

        else:
            pg = st.navigation(
                {
                    "Chat": [chat],
                },
                position="top",
            )

        pg.run()
        logger.info("User authenticated, showing main app pages. ")


if __name__ == "__main__":
    main()
