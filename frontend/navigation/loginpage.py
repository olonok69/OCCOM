import logging

import streamlit as st  # type: ignore
from msal import (
    PublicClientApplication,
    ConfidentialClientApplication,
    SerializableTokenCache,
)
import os
from dotenv import load_dotenv
import time
import secrets
import requests
import base64
from utils import generate_streamlit_config
from apis_calls.superadmin_apis import get_bot_config
from apis_calls.session_apis import get_session_titles


logger = logging.getLogger(__name__)
FRONT_EXCEPTION_TAG = "FRONT_EXCEPTION"

load_dotenv()

st.set_page_config(page_title="Login", layout="wide", initial_sidebar_state="collapsed")

OAUTH_AZURE_CLIENT_ID = os.getenv("OAUTH_AZURE_CLIENT_ID")
OAUTH_AZURE_CLIENT_SECRET = os.getenv("OAUTH_AZURE_CLIENT_SECRET")
OAUTH_AZURE_TENANT_ID = os.getenv(
    "OAUTH_AZURE_TENANT_ID", "common"
)  # Default to 'common' for multi-tenant
AUTHORITY = f"https://login.microsoftonline.com/{OAUTH_AZURE_TENANT_ID}"
SCOPES = ["User.Read"]  # Microsoft Graph User.Read scope
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:5000")
TOKEN_CACHE_FILE = "token_cache.bin"


def get_token_cache():
    """Get or create a persistent token cache."""
    cache = SerializableTokenCache()

    return cache


def get_persistent_auth_result():
    """Get authentication result from persistent storage."""
    if "persistent_auth_result" in st.session_state:
        auth_result = st.session_state.persistent_auth_result

        # Check if token is still valid (not expired)
        if auth_result and "expires_in" in auth_result and "timestamp" in auth_result:
            expires_at = auth_result["timestamp"] + auth_result["expires_in"]
            current_time = time.time()
            if current_time < expires_at - 300:  # 5 minutes buffer
                return auth_result
            else:
                logger.debug("Token expired, clearing persistent auth result")

        # Token expired or invalid, clear it
        del st.session_state.persistent_auth_result
    else:
        logger.debug("No persistent_auth_result found in session state")

    return None


def save_persistent_auth_result(auth_result):
    """Save authentication result to persistent storage."""
    if auth_result and "access_token" in auth_result:
        # Add timestamp for expiration checking
        auth_result["timestamp"] = time.time()
        st.session_state.persistent_auth_result = auth_result


def create_msal_app(use_confidential=True):
    """Create and return MSAL Application instance with persistent token cache."""
    cache = get_token_cache()

    if use_confidential and OAUTH_AZURE_CLIENT_SECRET:
        # Use ConfidentialClientApplication for redirect flow with client secret
        app = ConfidentialClientApplication(
            OAUTH_AZURE_CLIENT_ID,
            client_credential=OAUTH_AZURE_CLIENT_SECRET,
            authority=AUTHORITY,
            token_cache=cache,
        )
    else:
        # Use PublicClientApplication for PKCE flow
        app = PublicClientApplication(
            OAUTH_AZURE_CLIENT_ID, authority=AUTHORITY, token_cache=cache
        )

    # Save cache after creating app (in case it was modified)
    # save_token_cache(cache)
    return app


def handle_callback():
    """Handle the OAuth callback from Microsoft."""
    # Check if we have query parameters (callback from Microsoft)
    query_params = st.query_params

    if "code" in query_params and "state" in query_params:
        auth_code = query_params["code"]
        state = query_params["state"]

        # Try to get stored state from session state, but if not available,
        # we'll accept the state (this can happen due to Streamlit session clearing)
        stored_state = st.session_state.get("oauth_state")

        if stored_state and stored_state != state:
            st.error(
                f"State mismatch. Expected: {stored_state[:10]}..., Got: {state[:10]}..."
            )
            st.error("Invalid state parameter. Please try signing in again.")
            # Clear query params to restart
            st.query_params.clear()
            return None

        # If no stored state (session was cleared), we'll proceed silently
        # This can happen due to Streamlit session clearing, but it's safe to continue

        return auth_code

    if "error" in query_params:
        error = query_params["error"]
        error_description = query_params.get("error_description", "Unknown error")
        st.error(f"Authentication error: {error} - {error_description}")
        return None

    return None


def get_user_info(access_token):
    """Get user information from Microsoft Graph API."""
    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        response = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Failed to get user info: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Error getting user info: {str(e)}")
        return None


def handle_auth_flow():
    """Handle the authentication flow with MSAL using PKCE."""
    # Use public client for PKCE flow
    app = create_msal_app(use_confidential=True)

    # Initialize session state
    if "user_info" not in st.session_state:
        st.session_state.user_info = None

    # Check for persistent authentication first
    persistent_auth = get_persistent_auth_result()
    if persistent_auth:
        st.session_state.auth_result = persistent_auth
        return persistent_auth

    # Check if user is already authenticated in current session
    if (
        "auth_result" in st.session_state
        and st.session_state.auth_result
        and "access_token" in st.session_state.auth_result
    ):
        return st.session_state.auth_result

    # Handle OAuth callback first
    auth_code = handle_callback()
    if auth_code:
        try:
            # Exchange authorization code for tokens using confidential client
            result = app.acquire_token_by_authorization_code(
                auth_code, scopes=SCOPES, redirect_uri=REDIRECT_URI
            )

            if "access_token" in result:
                # Save to both session state and persistent storage
                st.session_state.auth_result = result
                save_persistent_auth_result(result)

                # Save token cache to file
                # save_token_cache(app.token_cache)

                # Clear OAuth state
                if "oauth_state" in st.session_state:
                    del st.session_state.oauth_state

                # Clear query parameters to clean up URL
                st.query_params.clear()

                # Authentication successful - will redirect automatically
                st.rerun()
            else:
                error_msg = result.get(
                    "error_description", result.get("error", "Unknown error")
                )
                st.error(f"Token exchange failed: {error_msg}")
                # Clear query params on error
                st.query_params.clear()
        except Exception as e:
            st.error(f"Error during token exchange: {str(e)}")
            # Clear query params on error
            st.query_params.clear()

        return None

    # Check for existing accounts in cache and try to refresh token
    accounts = app.get_accounts()
    if accounts:
        st.info("Found existing account(s) in cache.")
        chosen_account = accounts[0]
        st.write(f"Account: {chosen_account.get('username', 'Unknown')}")

        # Try to acquire token silently (this will use refresh token if needed)
        result = app.acquire_token_silent(SCOPES, account=chosen_account)
        if result and "access_token" in result:
            # Save refreshed token to persistent storage
            st.session_state.auth_result = result
            save_persistent_auth_result(result)
            # save_token_cache(app.token_cache)
            st.success("🔁 Token refreshed automatically!")
            return result
        else:
            st.warning("Silent token acquisition failed. Need to sign in.")

    # Show sign-in options
    # Generate state and auth URL upfront for the sign-in button
    # Only generate if not already in session (preserves state across reruns)
    if "oauth_state" not in st.session_state:
        # Generate fresh state parameter (no PKCE needed for confidential client)
        state = secrets.token_urlsafe(32)
        st.session_state.oauth_state = state

    # Build authorization URL using stored state
    auth_url = app.get_authorization_request_url(
        scopes=SCOPES, state=st.session_state.oauth_state, redirect_uri=REDIRECT_URI
    )

    # Use HTML anchor with target="_self" to open in same tab instead of new tab
    # This ensures OAuth redirect comes back to the same Streamlit session
    escaped_auth_url = auth_url.replace('"', "&quot;")
    st.markdown(
        f"""
        <div style="text-align:center;">
        <a href="{escaped_auth_url}" target="_self">
            <button style="
                background-color: #0078d4;
                color: white;
                padding: 0.75rem 1.5rem;
                border: none;
                border-radius: 0.5rem;
                text-align: center;
                font-weight: 600;
                cursor: pointer;
                width: 50%;
                font-size: 1rem;
            ">
                🔒 Sign In with Microsoft
            </button>
        </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    return None


# --- Branding Header (centered logo + welcome text) ---
try:
    # Try to fetch config early (config endpoint is public)
    if not st.session_state.get("bot_config"):
        st.session_state["bot_config"] = get_bot_config() or {}
except Exception:
    logger.exception("%s loginpage.bot_config_fetch_failed", FRONT_EXCEPTION_TAG)

cfg = st.session_state.get("bot_config", {})
bot_name = cfg.get("bot_name", "Chat")
branding = st.session_state.get("branding_bytes", {})
logo = branding.get("logo") or branding.get("bot_icon")

_, c, _ = st.columns([1, 2, 1])
with c:
    if logo:
        try:
            b64 = base64.b64encode(logo).decode("utf-8")
            st.markdown(
                f"""
                <div style='text-align:center;'>
                  <img src="data:image/png;base64,{b64}" style="display:block;margin:0 auto;width:140px;" />
                </div>
                """,
                unsafe_allow_html=True,
            )
        except Exception:
            st.image(logo, width=140)
    st.markdown(
        f"<h2 style='text-align:center; margin: 0.5rem 0 0 0;'>Welcome to {bot_name}</h2>",
        unsafe_allow_html=True,
    )

auth_result = handle_auth_flow()

if auth_result and "access_token" in auth_result:
    st.success("✅ Successfully authenticated!")

    st.session_state["token"] = auth_result["access_token"]
    st.session_state["id_token"] = auth_result.get("id_token", "")

    try:
        roles = auth_result.get("id_token_claims", {}).get("roles", [])
        # Check for highest role: super-admin > admin > user
        if "super-admin" in roles:
            st.session_state["role"] = "super-admin"
        elif "admin" in roles:
            st.session_state["role"] = "admin"
        elif "user" in roles:
            st.session_state["role"] = "user"
        else:
            st.session_state["role"] = "user"
    except KeyError:
        st.session_state["role"] = "user"

    st.session_state["is_authenticated"] = True
    st.session_state["username"] = auth_result.get("id_token_claims", {}).get(
        "name", "Unknown User"
    )

    # Get bot_id from environment variable instead of JWT token
    bot_id = os.getenv("BOT_ID", "default")
    st.session_state["user_id"] = auth_result["id_token_claims"].get(
        "oid", "unknown_user"
    )
    st.session_state["bot_id"] = bot_id

    # Fetch session titles once during login and cache them
    try:
        titles_result = get_session_titles()
        if titles_result and titles_result.get("success"):
            st.session_state["cached_session_titles"] = titles_result.get(
                "session_titles", {}
            )
        else:
            st.session_state["cached_session_titles"] = {}
    except Exception:
        st.session_state["cached_session_titles"] = {}

    generate_streamlit_config()

    st.rerun()
else:
    st.session_state["is_authenticated"] = False
    st.session_state["id_token"] = ""
    st.session_state["role"] = ""
    st.session_state["token"] = ""
