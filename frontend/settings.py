import os
import streamlit as st
from dotenv import load_dotenv


class Settings:
    """Centralized access to frontend settings and auth.

    Provides a single place to read environment-configured values and
    to construct standard headers based on the current Streamlit session.
    """

    def __init__(self) -> None:
        load_dotenv()

    @property
    def backend_base_url(self) -> str:
        return os.getenv("BACKEND_API_BASE_URL", "http://127.0.0.1:8000")

    @property
    def frontend_base_url(self) -> str:
        return os.getenv("FRONTEND_BASE_URL", "http://127.0.0.1:8501")

    @property
    def bot_id(self) -> str:
        return os.getenv("BOT_ID", "bot_test_1234")

    @property
    def auth_token(self) -> str:
        return st.session_state.get("id_token", "")

    @property
    def is_debug(self) -> bool:
        return os.getenv("DEBUG", "false").lower() == "true"

    @property
    def is_show_auth_token(self) -> bool:
        return os.getenv("SHOW_AUTH_TOKEN", "false").lower() == "true"

    @property
    def max_tabs(self) -> int:
        return int(os.getenv("MAX_TABS", "5"))

    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO")

    def build_headers(
        self, session_id: str | None = None, message_id: str | None = None
    ) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": os.getenv("OCP_APIM_SUBSCRIPTION_KEY", ""),
            "BotID": self.bot_id,
        }
        if session_id:
            headers["SessionID"] = session_id
        if message_id:
            headers["MessageID"] = message_id
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        return headers


# Module-level singleton for convenience
settings = Settings()
