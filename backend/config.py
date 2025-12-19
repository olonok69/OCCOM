from dotenv import load_dotenv
import os
import logging
from service.blob_storage import get_bot_config_from_blob

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    """Configuration settings for the application, loaded from environment variables."""

    def __init__(self):
        # Azure OpenAI Configuration
        self.azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_openai_api_version = os.getenv(
            "AZURE_OPENAI_API_VERSION", "2024-12-01-preview"
        )
        self.azure_openai_deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        self.azure_openai_embedding_deployment = os.getenv(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        )

        # Azure AI Search Configuration
        self.azure_search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
        self.azure_search_service_name = os.getenv("AZURE_SEARCH_SERVICE_NAME")

        # If service name is not provided but endpoint is, extract it from the endpoint
        if not self.azure_search_service_name and self.azure_search_endpoint:
            # Extract service name from endpoint URL like https://service-name.search.windows.net
            import urllib.parse

            parsed_url = urllib.parse.urlparse(self.azure_search_endpoint)
            if parsed_url.hostname and parsed_url.hostname.endswith(
                ".search.windows.net"
            ):
                self.azure_search_service_name = parsed_url.hostname.replace(
                    ".search.windows.net", ""
                )
                logger.debug(
                    f"Extracted Azure Search service name '{self.azure_search_service_name}' from endpoint '{self.azure_search_endpoint}'"
                )

        self.azure_search_index_name = os.getenv("AZURE_SEARCH_INDEX_NAME")
        # Note: Admin key is not required - the application uses Azure Managed Identity for authentication

        # Azure Storage Configuration
        self.azure_storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        self.azure_storage_container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME")

        # Model Configuration
        self.embedding_model_name = os.getenv(
            "EMBEDDING_MODEL_NAME", "text-embedding-3-large"
        )
        self.llm_model_name = os.getenv("LLM_MODEL_NAME", "gpt-4o")

        self.chunk_size = int(os.getenv("CHUNK_SIZE", "1024"))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "200"))

        # RAG Prompt Template

        # Bot Configuration from YAML
        self.bot_config = self._load_bot_config()
        self.has_filters = self.bot_config.get("has_filters", False)
        self.filters = self.bot_config.get("filters", [])
        self.filter_mapping = self.bot_config.get("filter_mapping", {})
        self.look_and_feel = self.bot_config.get("look_and_feel", {})
        self.required_headers = self.bot_config.get("required_headers", [])
        self.rag_prompt_template = self.bot_config.get("prompt_template", "")
        self.system_prompt = self.bot_config.get("system_prompt", "")

        # Chat History Service Configuration
        self.chat_history_api_url = os.getenv(
            "CHAT_HISTORY_API_URL",
            "https://app-apps-dev-uks-biabv2chathistory-1.azurewebsites.net/",
        )
        self.chat_history_enabled = (
            os.getenv("CHAT_HISTORY_ENABLED", "true").lower() == "true"
        )

        # Bot Configuration
        self.bot_id = os.getenv("BOT_ID", "document-assistant")

        # Azure AD JWT Authentication settings
        self.azure_ad_tenant_id = os.getenv("OAUTH_AZURE_TENANT_ID")
        self.azure_ad_audience = os.getenv(
            "OAUTH_AZURE_CLIENT_ID"
        )  # The audience for your API  # Optional: defaults to client_id
        self.use_chapter_chunking = (
            os.getenv("USE_CHAPTER_CHUNKING", "false").lower() == "true"
        )
        # Validate config after all attributes are set
        self.validate_config()

    def validate_config(self):
        """Validate that all required configuration values are set."""
        required_configs = [
            ("AZURE_OPENAI_ENDPOINT", self.azure_openai_endpoint),
            ("AZURE_OPENAI_DEPLOYMENT_NAME", self.azure_openai_deployment_name),
            (
                "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
                self.azure_openai_embedding_deployment,
            ),
        ]

        # Optional configs - warn if missing but don't fail
        optional_configs = [
            (
                "AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_SERVICE_NAME",
                self.azure_search_service_name,
            ),
            ("AZURE_SEARCH_INDEX_NAME", self.azure_search_index_name),
            ("AZURE_STORAGE_ACCOUNT_NAME", self.azure_storage_account_name),
            ("AZURE_STORAGE_CONTAINER_NAME", self.azure_storage_container_name),
        ]

        # Azure AD JWT Authentication configs - required for JWT validation
        jwt_auth_configs = [
            ("OAUTH_AZURE_TENANT_ID", self.azure_ad_tenant_id),
            ("OAUTH_AZURE_CLIENT_ID", self.azure_ad_audience),
        ]

        missing_configs = [name for name, value in required_configs if not value]
        if missing_configs:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_configs)}"
            )

        # Check JWT authentication configs
        missing_jwt_configs = [name for name, value in jwt_auth_configs if not value]
        if missing_jwt_configs:
            logger.warning(
                "Warning: Missing Azure AD JWT authentication configurations: %s",
                ", ".join(missing_jwt_configs),
            )
            logger.warning(
                "JWT authentication will be disabled. Set these environment variables to enable JWT auth."
            )

        missing_optional = [name for name, value in optional_configs if not value]
        if missing_optional:
            logger.warning(
                f"Missing optional environment variables (file processing will be disabled): {', '.join(missing_optional)}"
            )

        return True

    def _load_bot_config(self):
        """Load bot configuration from Azure Blob Storage with fallback to defaults"""
        # First, load default config
        default_config = {}
        try:
            import json
            from pathlib import Path

            default_config_path = Path(__file__).parent / "default-config.json"
            if default_config_path.exists():
                with open(default_config_path, "r", encoding="utf-8") as f:
                    default_config = json.load(f)
                    logger.debug(
                        f"Loaded default config with {len(default_config)} keys"
                    )
        except Exception as e:
            logger.warning(f"Failed to load default config: {e}")

        # Then try to load from blob storage and merge
        if self.azure_storage_account_name and self.azure_storage_container_name:
            try:
                blob_config = get_bot_config_from_blob(
                    account_name=self.azure_storage_account_name,
                    container_name=self.azure_storage_container_name,
                    blob_name="config.json",
                )
                if blob_config:
                    # Merge blob config with defaults (blob config takes precedence)
                    merged_config = {**default_config, **blob_config}
                    return merged_config
                else:
                    logger.warning(
                        "config.json not found in blob storage, using defaults"
                    )
                    return default_config
            except Exception as e:
                logger.warning(
                    f"Failed to load bot config from blob storage: {e}, using defaults"
                )
                return default_config
        else:
            return default_config

    @property
    def filter_fields(self):
        """Get list of filter field names"""
        if self.has_filters and self.filters:
            # Handle both dict and list formats
            if isinstance(self.filters, dict):
                return list(self.filters.values())
            elif isinstance(self.filters, list):
                return self.filters
        return []

    def get_filter_field_name(self, filter_key):
        """Get the field name for a filter key"""
        if self.has_filters and self.filters:
            return self.filters.get(filter_key, filter_key)
        return filter_key

    def create_filter_dict(self, data_dict):
        """Create filter dictionary with only configured filter fields"""
        filter_data = {}
        for field in self.filter_fields:
            if field in data_dict:
                filter_data[field] = data_dict[field]
        return filter_data

    def reload_config(self):
        """
        Reload bot configuration from blob storage or local file.
        Used after factory reset to load default configuration.
        """
        try:
            # Reload bot config
            if self.azure_storage_account_name and self.azure_storage_container_name:
                try:
                    bot_config = get_bot_config_from_blob(
                        account_name=self.azure_storage_account_name,
                        container_name=self.azure_storage_container_name,
                        blob_name="config.json",
                    )
                    if bot_config:
                        self.bot_config = bot_config
                    else:
                        logger.warning(
                            "[WARNING] [CONFIG RELOAD] config.json not found in blob storage, using defaults"
                        )
                        self.bot_config = {}
                except Exception as e:
                    logger.warning(
                        f"[WARNING] [CONFIG RELOAD] Failed to reload from blob: {e}, using defaults"
                    )
                    self.bot_config = {}
            else:
                # Try to load from local file
                try:
                    import json

                    with open("config.json", "r", encoding="utf-8") as f:
                        self.bot_config = json.load(f)
                except FileNotFoundError:
                    logger.warning(
                        "[WARNING] [CONFIG RELOAD] config.json not found locally, using defaults"
                    )
                    self.bot_config = {}
                except Exception as e:
                    logger.error(f"[ERROR] [CONFIG RELOAD] Error loading local config: {e}")
                    self.bot_config = {}

            # Update derived configuration attributes
            self.has_filters = self.bot_config.get("has_filters", False)
            self.filters = self.bot_config.get("filters", [])
            self.filter_mapping = self.bot_config.get("filter_mapping", {})

            self.bot_name = self.bot_config.get("bot_name")
            self.version = self.bot_config.get("version")
            self.language = self.bot_config.get("language")
            self.about_text = self.bot_config.get("about_text")
            self.disclaimer_text = self.bot_config.get("disclaimer_text")
            self.primary_color = self.bot_config.get("primary_color")
            self.secondary_background_color = self.bot_config.get(
                "secondary_background_color"
            )
            self.background_color = self.bot_config.get("background_color")
            self.text_color = self.bot_config.get("text_color")
            self.font_family = self.bot_config.get("font_family")
            self.font_size = self.bot_config.get("font_size")
            self.welcome_message = self.bot_config.get("welcome_message")
            self.default_response = self.bot_config.get("default_response")
            self.feedback_contact_name = self.bot_config.get("feedback_contact_name")
            self.feedback_contact_email = self.bot_config.get("feedback_contact_email")
            self.system_prompt = self.bot_config.get("system_prompt")

            self.required_headers = self.bot_config.get("required_headers", [])
            self.system_prompt = self.bot_config.get("system_prompt", "")

        except Exception as ex:
            logger.error(f"[ERROR] [CONFIG RELOAD] Error during config reload: {ex}")
            self.bot_config = {}
            # Reset to defaults on error
            self.has_filters = False
            self.filters = []
            self.filter_mapping = {}
            self.look_and_feel = {}
            self.required_headers = []
            self.system_prompt = ""
