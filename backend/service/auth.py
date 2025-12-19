"""
JWT Authentication Service

This module provides JWT token validation and role-based access control.
"""

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import base64
from typing import Dict, Any
from fastapi import HTTPException, status
from config import Config
from model.apis import UserRole
import logging

logger = logging.getLogger("main")


class JWTAuthService:
    """Azure AD JWT Authentication Service using Managed Identity for validation"""

    def __init__(self, config: Config):
        """Initialize the JWT service with Azure AD configuration"""
        self.tenant_id = config.azure_ad_tenant_id
        self.audience = config.azure_ad_audience

        if not self.tenant_id:
            raise ValueError("Azure AD Tenant ID is required")
        if not self.audience:
            raise ValueError("Azure AD Audience is required")

        # Azure AD endpoints
        self.jwks_url = (
            f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"
        )
        self.issuer = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

        # Cache for public keys
        self._public_keys_cache = None
        self._cache_timestamp = None

        logger.info(f"JWT Auth Service initialized for tenant: {self.tenant_id}")
        logger.info(f"Expected audience: {self.audience}")
        logger.info(f"JWKS URL: {self.jwks_url}")
        logger.info(f"Issuer: {self.issuer}")

    def _get_public_keys(self) -> Dict[str, Any]:
        """
        Fetch and cache Azure AD public keys for JWT validation.
        Uses simple time-based caching to avoid excessive API calls.
        """
        import time

        # Simple cache check (cache for 1 hour)
        current_time = time.time()
        if (
            self._public_keys_cache is not None
            and self._cache_timestamp is not None
            and current_time - self._cache_timestamp < 3600
        ):
            return self._public_keys_cache

        try:
            logger.info(f"Fetching public keys from: {self.jwks_url}")
            response = requests.get(self.jwks_url, timeout=10)
            response.raise_for_status()

            jwks_data = response.json()
            public_keys = {}

            for key_data in jwks_data.get("keys", []):
                kid = key_data.get("kid")
                if not kid:
                    continue

                # Convert JWK to PEM format
                try:
                    # Extract RSA components
                    n = base64.urlsafe_b64decode(key_data["n"] + "==")
                    e = base64.urlsafe_b64decode(key_data["e"] + "==")

                    # Convert to integers
                    n_int = int.from_bytes(n, "big")
                    e_int = int.from_bytes(e, "big")

                    # Create RSA public key
                    public_key = rsa.RSAPublicNumbers(e_int, n_int).public_key()

                    # Convert to PEM format
                    pem_key = public_key.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )

                    public_keys[kid] = pem_key

                except Exception as key_error:
                    logger.warning(f"Failed to process key {kid}: {key_error}")
                    continue

            # Update cache
            self._public_keys_cache = public_keys
            self._cache_timestamp = current_time

            logger.info(f"Successfully cached {len(public_keys)} public keys")
            return public_keys

        except Exception as e:
            logger.error(f"Failed to fetch public keys: {e}")
            # Return cached keys if available, even if expired
            if self._public_keys_cache:
                logger.warning("Using expired cached keys due to fetch failure")
                return self._public_keys_cache
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to validate JWT tokens - key service unavailable",
            )

    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        Decode and validate Azure AD JWT token using public keys.

        Args:
            token: JWT token string

        Returns:
            Decoded token payload

        Raises:
            HTTPException: If token is invalid or expired
        """
        try:
            # Get token header to extract key ID

            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            if not kid:
                logger.warning("JWT token missing key ID (kid) in header")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token format - missing key ID",
                )

            # Get public keys
            public_keys = self._get_public_keys()

            if kid not in public_keys:
                logger.warning(f"Unknown key ID: {kid}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token - unknown key ID",
                )

            # Decode and validate token
            try:
                payload = jwt.decode(
                    token,
                    public_keys[kid],
                    algorithms=["RS256"],
                    audience=self.audience,
                    issuer=self.issuer,
                    options={
                        "verify_signature": True,
                        "verify_exp": True,
                        "verify_aud": True,
                        "verify_iss": True,
                    },
                )

                logger.debug(
                    f"Successfully decoded token for user: {payload.get('preferred_username', 'unknown')}"
                )
                return payload

            except jwt.ExpiredSignatureError:
                logger.error("JWT token has expired")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired"
                )
            except jwt.InvalidAudienceError:
                logger.error(f"Invalid audience in token. Expected: {self.audience}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token audience",
                )
            except jwt.InvalidIssuerError:
                logger.error(f"Invalid issuer in token. Expected: {self.issuer}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token issuer",
                )
            except jwt.InvalidTokenError as e:
                logger.error(f"Invalid JWT token: {e}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
                )

        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error decoding JWT token: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Token validation error",
            )

    def validate_user_role(self, payload: Dict[str, Any]) -> bool:
        """
        Validate if the user has a valid role from Azure AD token.

        Args:
            payload: Decoded JWT token payload

        Returns:
            True if user has a valid role, False otherwise
        """
        # Azure AD tokens may contain roles in different claims
        # Check common role claims used in Azure AD
        roles = []

        # Check 'roles' claim (app roles)
        if "roles" in payload:
            roles.extend(payload["roles"])

        # Check 'groups' claim (security groups) - if configured
        if "groups" in payload:
            roles.extend(payload["groups"])

        # Check custom role claim if configured
        if "extension_Role" in payload:
            roles.append(payload["extension_Role"])

        # Check if any role matches our expected roles
        valid_roles = {role.value for role in UserRole}
        user_roles = set(roles)

        has_valid_role = bool(user_roles.intersection(valid_roles))

        if not has_valid_role:
            logger.info(
                f"User has no valid roles, assigning default USER role. User roles: {user_roles}, Valid roles: {valid_roles}"
            )
            # Assign USER as default role when no valid roles are found
            payload["roles"] = [UserRole.USER.value]
            return True

        return has_valid_role

    def get_user_info(self, token: str) -> Dict[str, Any]:
        """
        Extract user information from Azure AD JWT token.

        Args:
            token: JWT token string

        Returns:
            Dictionary containing user information

        Raises:
            HTTPException: If token is invalid or user has insufficient permissions
        """
        # Remove 'Bearer ' prefix if present
        if token.startswith("Bearer "):
            token = token[7:]

        # Decode token
        payload = self.decode_token(token)

        # Validate user has valid role
        if not self.validate_user_role(payload):
            logger.warning("User does not have valid role for access")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions - invalid or missing role",
            )

        # Extract user information from Azure AD token
        user_info = {
            "user_id": payload.get("oid") or payload.get("sub"),  # Object ID or Subject
            "username": payload.get("preferred_username")
            or payload.get("upn"),  # Username or UPN
            "email": payload.get("email") or payload.get("preferred_username"),
            "name": payload.get("name"),
            "given_name": payload.get("given_name"),
            "family_name": payload.get("family_name"),
            "tenant_id": payload.get("tid"),
            "app_id": payload.get("appid"),
            "roles": [],
            "token_payload": payload,  # Include full payload for additional claims
        }

        # Extract roles from various claims
        if "roles" in payload:
            user_info["roles"].extend(payload["roles"])
        if "groups" in payload:
            user_info["roles"].extend(payload["groups"])
        if "extension_Role" in payload:
            user_info["roles"].append(payload["extension_Role"])

        logger.info(f"Retrieved user info for: {user_info.get('username', 'unknown')}")
        return user_info


# Create a global instance of the JWT auth service
# This will be initialized when the application starts
jwt_auth_service = None


def initialize_jwt_service(config: Config):
    """Initialize the global JWT authentication service."""
    global jwt_auth_service
    jwt_auth_service = JWTAuthService(config)
    return jwt_auth_service
