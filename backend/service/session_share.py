"""
Session Share Service for managing shareable session links

This service handles creating, validating, and revoking share tokens for chat sessions.
Sessions are private by default. When shared, a token is created that allows public access.
"""

import secrets
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
BACKEND_EXCEPTION_TAG = "BACKEND_EXCEPTION"


class SessionShareService:
    """Service for managing shareable session links"""

    def __init__(self, chat_history_service=None, bot_id: Optional[str] = None):
        """
        Initialize the session share service with CosmosDB storage via chat history service.

        Args:
            chat_history_service: ChatHistoryService instance for CosmosDB operations
            bot_id: Bot identifier (required for CosmosDB queries)
        """
        self.chat_history_service = chat_history_service
        self.bot_id = bot_id
        # Fallback in-memory storage for backward compatibility (if chat_history_service not available)
        self.share_tokens: Dict[str, Dict[str, Any]] = {}

        if self.chat_history_service:
            logger.info(
                "SessionShareService initialized with CosmosDB storage via chat history service"
            )
        else:
            logger.warning(
                "SessionShareService initialized with in-memory storage (chat_history_service not provided)"
            )

    def create_share_token(
        self,
        session_id: str,
        user_id: str,
        bot_id: str,
        expires_in_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Create a share token for a session.

        Args:
            session_id: Session identifier
            user_id: User identifier (session owner)
            bot_id: Bot identifier
            expires_in_days: Number of days until token expires (default: 30)

        Returns:
            Dict containing:
                - share_token: Unique token for sharing (internal use only)
                - expires_at: ISO timestamp when token expires
                - created_at: ISO timestamp when token was created
        """
        try:
            # Generate a secure random token
            share_token = secrets.token_urlsafe(32)

            # Calculate expiration
            created_at = datetime.now(timezone.utc)
            expires_at = created_at + timedelta(days=expires_in_days)

            # Mark session messages as public via PATCH endpoint
            use_cosmosdb = False
            if self.chat_history_service:
                # PATCH endpoint sets public=True for all messages in the session
                result = self.chat_history_service.patch_session_make_public(
                    session_id=session_id,
                    user_id=user_id,
                    bot_id=bot_id,
                )

                if result["success"]:
                    logger.info(
                        f"[INFO] [SHARE] Marked session {session_id} as public (set public=True for all messages) by user {user_id}"
                    )
                    use_cosmosdb = True
                else:
                    error_msg = result.get("error", "Unknown error")
                    # If endpoint doesn't exist (404), fall back to in-memory storage
                    if "404" in error_msg or "Not Found" in error_msg:
                        logger.warning(
                            f"[WARNING] [SHARE] PATCH endpoint not available (404). "
                            f"Falling back to in-memory storage for session {session_id}"
                        )
                        use_cosmosdb = False
                    else:
                        logger.error(
                            f"[ERROR] [SHARE] Failed to mark session as public: {error_msg}"
                        )
                        raise Exception(
                            f"Failed to mark session as public: {error_msg}"
                        )

            # Fallback to in-memory storage (if CosmosDB not available or endpoint not implemented)
            if not use_cosmosdb:
                token_metadata = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "bot_id": bot_id,
                    "created_at": created_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "is_active": True,
                }
                self.share_tokens[share_token] = token_metadata
                logger.warning(
                    f"[WARNING] [SHARE] Created share token in memory (CosmosDB not available or endpoint not implemented) for session {session_id}"
                )

            return {
                "share_token": share_token,
                "expires_at": expires_at.isoformat(),
                "created_at": created_at.isoformat(),
            }

        except Exception as e:
            logger.error(f"[ERROR] [SHARE] Error creating share token: {str(e)}")
            raise

    def get_share_token_info(
        self,
        share_token: str,
        user_id: Optional[str] = None,
        bot_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get share token metadata if token exists and is valid.

        Args:
            share_token: Share token to validate
            user_id: Optional user identifier (not required if querying by share_token)
            bot_id: Optional bot identifier (uses self.bot_id if not provided)

        Returns:
            Dict with token metadata if valid, None otherwise
        """
        # Use CosmosDB if chat history service is available
        if self.chat_history_service:
            bot_id_to_use = bot_id or self.bot_id
            if not bot_id_to_use:
                logger.error(
                    "[ERROR] [SHARE] bot_id is required for CosmosDB query but not provided"
                )
                return None

            # Query by share_token (no user_id needed)
            result = self.chat_history_service.get_session_metadata_by_share_token(
                share_token=share_token,
                bot_id=bot_id_to_use,
            )

            if not result["success"]:
                logger.error(
                    f"[ERROR] [SHARE] Error getting share token info: {result.get('error')}"
                )
                return None

            metadata = result.get("data")
            if not metadata:
                logger.warning(
                    f"[WARNING] [SHARE] Share token not found: {share_token[:10]}..."
                )
                return None

            # Check if token is expired
            expires_at_str = metadata.get("share_token_expires_at")
            if expires_at_str:
                try:
                    expires_at = datetime.fromisoformat(
                        expires_at_str.replace("Z", "+00:00")
                    )
                    if datetime.now(timezone.utc) > expires_at:
                        logger.warning(
                            f"[WARNING] [SHARE] Share token expired: {share_token[:10]}..."
                        )
                        return None
                except Exception as e:
                    logger.error(f"[ERROR] [SHARE] Error parsing expiration: {str(e)}")
                    return None

            # Check if session is still public
            if not metadata.get("is_public", False):
                logger.warning(
                    f"[WARNING] [SHARE] Share token is inactive (session no longer public): {share_token[:10]}..."
                )
                return None

            # Return in the same format as in-memory storage for compatibility
            return {
                "session_id": metadata.get("SessionID"),
                "user_id": metadata.get("UserID"),
                "bot_id": metadata.get("BotID"),
                "created_at": metadata.get("share_token_created_at"),
                "expires_at": metadata.get("share_token_expires_at"),
                "is_active": metadata.get("is_public", False),
            }

        # Fallback to in-memory storage
        if share_token not in self.share_tokens:
            logger.warning(f"[WARNING] [SHARE] Share token not found: {share_token[:10]}...")
            return None

        token_metadata = self.share_tokens[share_token]

        # Check if token is active
        if not token_metadata.get("is_active", False):
            logger.warning(f"[WARNING] [SHARE] Share token is inactive: {share_token[:10]}...")
            return None

        # Check if token is expired
        expires_at_str = token_metadata.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(
                    expires_at_str.replace("Z", "+00:00")
                )
                if datetime.now(timezone.utc) > expires_at:
                    logger.warning(
                        f"[WARNING] [SHARE] Share token expired: {share_token[:10]}..."
                    )
                    # Mark as inactive
                    token_metadata["is_active"] = False
                    return None
            except Exception as e:
                logger.error(f"[ERROR] [SHARE] Error parsing expiration: {str(e)}")
                return None

        return token_metadata

    def _try_get_user_id_from_session(
        self, session_id: str, bot_id: str
    ) -> Optional[str]:
        """
        Try to get user_id from session messages.
        This is a workaround when user_id is not available but we need to query CosmosDB.

        Note: This requires the chat history service API to support querying by session_id only,
        or we need to know at least one user_id that might have this session.

        Returns:
            User ID if found, None otherwise
        """
        # This is a limitation - we can't query CosmosDB by session_id alone without user_id
        # The chat history service API would need to support cross-partition queries
        # For now, return None
        return None

    def is_session_public(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        bot_id: Optional[str] = None,
        share_token: Optional[str] = None,
    ) -> bool:
        """
        Check if a session is currently public (has active share token).

        Args:
            session_id: Session identifier
            user_id: Optional user identifier (if not provided, will try to get from share_token)
            bot_id: Optional bot identifier (uses self.bot_id if not provided)
            share_token: Optional share token (if provided, will be used to get user_id)

        Returns:
            True if session has an active share token, False otherwise
        """
        # Use CosmosDB if chat history service is available
        if self.chat_history_service:
            bot_id_to_use = bot_id or self.bot_id
            if not bot_id_to_use:
                logger.error(
                    "[ERROR] [SHARE] bot_id is required for CosmosDB query but not provided"
                )
                return False

            # If user_id not provided, try to get it from share_token
            if not user_id and share_token:
                token_info = self.get_share_token_info(
                    share_token, bot_id=bot_id_to_use
                )
                if token_info:
                    user_id = token_info.get("user_id")
                    # Verify session_id matches
                    if token_info.get("session_id") != session_id:
                        logger.warning(
                            f"[WARNING] [SHARE] Share token session_id mismatch: expected {session_id}, got {token_info.get('session_id')}"
                        )
                        return False

            # Check if session is public by trying to get the public session
            # get_public_session will only succeed if all messages have public=True
            result = self.chat_history_service.get_public_session(
                session_id=session_id,
                bot_id=bot_id_to_use,
            )

            if result["success"]:
                # If we can get the public session, it means all messages have public=True
                logger.info(
                    f"[INFO] [SHARE] Session {session_id} is public (all messages have public=True)"
                )
                return True
            else:
                # Session is not public or doesn't exist
                logger.debug(
                    f"[DEBUG] [SHARE] Session {session_id} is not public: {result.get('error', 'Unknown error')}"
                )
                return False

        # Fallback to in-memory storage
        for token, metadata in self.share_tokens.items():
            if metadata.get("session_id") == session_id and metadata.get(
                "is_active", False
            ):
                # Check expiration
                expires_at_str = metadata.get("expires_at")
                if expires_at_str:
                    try:
                        expires_at = datetime.fromisoformat(
                            expires_at_str.replace("Z", "+00:00")
                        )
                        if datetime.now(timezone.utc) <= expires_at:
                            return True
                    except Exception:
                        logger.warning(
                            "%s session_share.expiry_validation_failed session_id=%s token=%s",
                            BACKEND_EXCEPTION_TAG,
                            session_id,
                            token,
                            exc_info=True,
                        )

        return False

    def get_public_session_user_id(
        self,
        session_id: str,
        bot_id: Optional[str] = None,
        share_token: Optional[str] = None,
    ) -> Optional[str]:
        """
        Get the user_id for a public session (from active share token in CosmosDB).

        Args:
            session_id: Session identifier
            bot_id: Optional bot identifier (uses self.bot_id if not provided)
            share_token: Optional share token (if provided, will be used to get user_id)

        Returns:
            User ID if session is public and has active token, None otherwise
        """
        # Use CosmosDB if chat history service is available
        if self.chat_history_service:
            bot_id_to_use = bot_id or self.bot_id
            if not bot_id_to_use:
                logger.error(
                    "[ERROR] [SHARE] bot_id is required for CosmosDB query but not provided"
                )
                return None

            # If share_token provided, use it to get user_id
            if share_token:
                token_info = self.get_share_token_info(
                    share_token, bot_id=bot_id_to_use
                )
                if token_info and token_info.get("session_id") == session_id:
                    return token_info.get("user_id")

            # If no share_token, we can't query without user_id
            # This is a limitation - need share_token or user_id
            logger.warning(
                "[WARNING] [SHARE] get_public_session_user_id requires share_token or user_id to query CosmosDB. "
                "Cannot determine user_id for session."
            )
            return None

        # Fallback to in-memory storage
        for token, metadata in self.share_tokens.items():
            if metadata.get("session_id") == session_id and metadata.get(
                "is_active", False
            ):
                # Check expiration
                expires_at_str = metadata.get("expires_at")
                if expires_at_str:
                    try:
                        expires_at = datetime.fromisoformat(
                            expires_at_str.replace("Z", "+00:00")
                        )
                        if datetime.now(timezone.utc) <= expires_at:
                            return metadata.get("user_id")
                    except Exception:
                        logger.warning(
                            "%s session_share.expiry_user_lookup_failed session_id=%s token=%s",
                            BACKEND_EXCEPTION_TAG,
                            session_id,
                            token,
                            exc_info=True,
                        )

        return None

    def get_session_share_info(
        self, session_id: str, user_id: str, bot_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get share information for a session (if it exists and belongs to user).

        Args:
            session_id: Session identifier
            user_id: User identifier (to verify ownership)
            bot_id: Optional bot identifier (uses self.bot_id if not provided)

        Returns:
            Dict with share info if found, None otherwise
        """
        # Use CosmosDB if chat history service is available
        if self.chat_history_service:
            bot_id_to_use = bot_id or self.bot_id
            if not bot_id_to_use:
                logger.error(
                    "[ERROR] [SHARE] bot_id is required for CosmosDB query but not provided"
                )
                return None

            result = self.chat_history_service.get_session_metadata(
                session_id=session_id,
                user_id=user_id,
                bot_id=bot_id_to_use,
            )

            if result["success"] and result.get("data"):
                metadata = result["data"]
                # Verify it belongs to the user
                if metadata.get("UserID") != user_id:
                    return None

                # Check if it's public and not expired
                if not metadata.get("is_public", False):
                    return None

                expires_at_str = metadata.get("share_token_expires_at")
                if expires_at_str:
                    try:
                        expires_at = datetime.fromisoformat(
                            expires_at_str.replace("Z", "+00:00")
                        )
                        if datetime.now(timezone.utc) > expires_at:
                            return None  # Expired
                    except Exception:
                        logger.warning(
                            "%s session_share.expiry_metadata_parse_failed session_id=%s",
                            BACKEND_EXCEPTION_TAG,
                            session_id,
                            exc_info=True,
                        )
                        return None

                return {
                    "share_token": metadata.get("share_token"),
                    "expires_at": metadata.get("share_token_expires_at"),
                    "created_at": metadata.get("share_token_created_at"),
                }

            return None

        # Fallback to in-memory storage
        for token, metadata in self.share_tokens.items():
            if (
                metadata.get("session_id") == session_id
                and metadata.get("user_id") == user_id
                and metadata.get("is_active", False)
            ):
                # Check expiration
                expires_at_str = metadata.get("expires_at")
                if expires_at_str:
                    try:
                        expires_at = datetime.fromisoformat(
                            expires_at_str.replace("Z", "+00:00")
                        )
                        if datetime.now(timezone.utc) > expires_at:
                            continue  # Expired, skip
                    except Exception:
                        logger.warning(
                            "%s session_share.expiry_metadata_fallback_parse_failed session_id=%s token=%s",
                            BACKEND_EXCEPTION_TAG,
                            session_id,
                            token,
                            exc_info=True,
                        )
                        continue

                return {
                    "share_token": token,
                    "expires_at": metadata.get("expires_at"),
                    "created_at": metadata.get("created_at"),
                }

        return None

    def revoke_share_token(
        self, session_id: str, user_id: str, bot_id: Optional[str] = None
    ) -> bool:
        """
        Revoke share token for a session (marks session as private).

        Args:
            session_id: Session identifier
            user_id: User identifier (to verify ownership)
            bot_id: Optional bot identifier (uses self.bot_id if not provided)

        Returns:
            True if token was revoked, False if not found or not owned by user
        """
        # Use CosmosDB if chat history service is available
        if self.chat_history_service:
            bot_id_to_use = bot_id or self.bot_id
            if not bot_id_to_use:
                logger.error(
                    "[ERROR] [SHARE] bot_id is required for CosmosDB update but not provided"
                )
                return False

            # Mark session as private by setting public=False for all messages
            patch_result = self.chat_history_service.patch_session_make_private(
                session_id=session_id,
                user_id=user_id,
                bot_id=bot_id_to_use,
            )

            if not patch_result["success"]:
                logger.error(
                    f"[ERROR] [SHARE] Failed to mark session as private: {patch_result.get('error')}"
                )
                return False

            # Also update session share metadata to clear share token info
            result = self.chat_history_service.make_session_public(
                session_id=session_id,
                user_id=user_id,
                bot_id=bot_id_to_use,
                is_public=False,
                share_token=None,
                share_token_expires_at=None,
                share_token_created_at=None,
            )

            if result["success"]:
                logger.info(
                    f"[INFO] [SHARE] Revoked share token for session {session_id} by user {user_id} (marked as private and updated metadata)"
                )
                return True
            else:
                logger.warning(
                    f"[WARNING] [SHARE] Session marked as private but metadata update failed: {result.get('error')}"
                )
                # Still return True since the main operation (making private) succeeded
                return True

        # Fallback to in-memory storage
        revoked_count = 0
        for token, metadata in self.share_tokens.items():
            if (
                metadata.get("session_id") == session_id
                and metadata.get("user_id") == user_id
            ):
                metadata["is_active"] = False
                revoked_count += 1
                logger.info(
                    f"[INFO] [SHARE] Revoked share token for session {session_id} by user {user_id}"
                )

        return revoked_count > 0

    def revoke_share_token_by_token(self, share_token: str, user_id: str) -> bool:
        """
        Revoke a specific share token (verify ownership first).

        Args:
            share_token: Share token to revoke
            user_id: User identifier (to verify ownership)

        Returns:
            True if token was revoked, False if not found or not owned by user
        """
        if share_token not in self.share_tokens:
            return False

        metadata = self.share_tokens[share_token]
        if metadata.get("user_id") != user_id:
            logger.warning(
                f"[WARNING] [SHARE] User {user_id} attempted to revoke token owned by {metadata.get('user_id')}"
            )
            return False

        metadata["is_active"] = False
        logger.info(
            f"[INFO] [SHARE] Revoked share token {share_token[:10]}... by user {user_id}"
        )
        return True

    def list_user_shares(self, user_id: str) -> list:
        """
        List all active share tokens created by a user.

        Args:
            user_id: User identifier

        Returns:
            List of share token metadata dicts
        """
        user_shares = []
        now = datetime.now(timezone.utc)

        for token, metadata in self.share_tokens.items():
            if metadata.get("user_id") == user_id and metadata.get("is_active", False):
                # Check expiration
                expires_at_str = metadata.get("expires_at")
                if expires_at_str:
                    try:
                        expires_at = datetime.fromisoformat(
                            expires_at_str.replace("Z", "+00:00")
                        )
                        if now > expires_at:
                            continue  # Expired, skip
                    except Exception:
                        logger.warning(
                            "%s session_share.list_user_shares_expiry_parse_failed user_id=%s token=%s",
                            BACKEND_EXCEPTION_TAG,
                            user_id,
                            token,
                            exc_info=True,
                        )
                        continue

                user_shares.append(
                    {
                        "share_token": token,
                        "session_id": metadata.get("session_id"),
                        "expires_at": metadata.get("expires_at"),
                        "created_at": metadata.get("created_at"),
                    }
                )

        return user_shares
