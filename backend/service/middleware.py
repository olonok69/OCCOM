"""
FastAPI Middleware for JWT Authentication

This middleware handles JWT authentication for all protected endpoints,
extracting and validating JWT tokens from the Authorization header.
"""

import logging
from typing import Dict, Any, Optional, List
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from model.apis import UserRole

logger = logging.getLogger(__name__)


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    JWT Authentication Middleware for FastAPI

    This middleware:
    1. Checks if the endpoint requires authentication
    2. Extracts JWT token from Authorization header
    3. Validates the token using Azure AD
    4. Adds user information to request state
    5. Handles role-based access control
    """

    def __init__(
        self, app, jwt_service=None, excluded_paths: Optional[List[str]] = None
    ):
        """
        Initialize JWT Authentication Middleware

        Args:
            app: FastAPI application instance
            jwt_service: JWT authentication service instance
            excluded_paths: List of paths to exclude from authentication
        """
        super().__init__(app)

        # Store JWT service reference
        self.jwt_service = jwt_service

        # Default excluded paths (public endpoints)
        default_excluded = ["/docs", "/redoc", "/openapi.json", "/favicon.ico"]

        self.excluded_paths = excluded_paths or default_excluded

        # Role-based access control lists
        # NoAuth: Public endpoints that don't require authentication
        self.no_auth_paths = [
            "/docs",
            "/redoc",
            "/openapi.json",
            "/favicon.ico",
            "/v1/health",
            "/v1/config",  # Public config endpoint for frontend
            "/v1/metadata-template",  # Public template download endpoint,
            "/v1/image",
            "/v1/public_session",  # Public session endpoint (no auth required)
        ]

        # User: Endpoints accessible by users, admins, and super admins
        self.user_paths = [
            "/v1/query",
            "/v1/status/",
            "/v1/chat/history",
            "/v1/chat/feedback",
            "/v1/chat/export",
            "/v1/session/",
            "/v1/ws/",
            "/v1/sessions/titles",
            "/v1/get-pdf/",
        ]

        # Admin: Endpoints accessible by admins and super admins only
        self.admin_paths = [
            "/v1/upload",
            "/v1/botids/",
            "/v1/files/",  # DELETE operations
            "/v1/bots/{bot_id}/statistics",
        ]

        # Super Admin: Endpoints accessible by super admins only
        self.super_admin_paths = [
            "/v1/updateconfig"
            # Add super admin exclusive endpoints here
            # Example: "/v1/admin/users", "/v1/admin/system"
        ]

        logger.info(
            f"JWT Auth Middleware initialized with {len(self.excluded_paths)} excluded paths"
        )

    async def dispatch(self, request: Request, call_next):
        """
        Process each request through the authentication middleware

        Args:
            request: FastAPI request object
            call_next: Next middleware/endpoint in the chain

        Returns:
            Response from the next middleware/endpoint or error response
        """

        # Check if path is excluded from authentication (NoAuth)
        if self._is_excluded_path(request.url.path) or self._is_no_auth_path(
            request.url.path
        ):
            logger.debug(f"Skipping auth for public path: {request.url.path}")
            return await call_next(request)

        try:
            # Extract and validate JWT token
            user_info = await self._authenticate_request(request)

            # Check role-based access
            self._check_role_access(request.url.path, request.method, user_info)

            # Add user info to request state for endpoints to access
            request.state.current_user = user_info

            logger.debug(
                f"Authentication successful for user: {user_info.get('username', 'unknown')}"
            )

            # Continue to the next middleware/endpoint
            response = await call_next(request)
            return response

        except HTTPException as e:
            logger.warning(f"Authentication failed for {request.url.path}: {e.detail}")
            return JSONResponse(
                status_code=e.status_code,
                content={"error": e.detail, "status_code": e.status_code},
            )
        except Exception as e:
            logger.error(f"Unexpected error in auth middleware: {str(e)}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": "Internal server error", "status_code": 500},
            )

    def _is_excluded_path(self, path: str) -> bool:
        """
        Check if the request path is excluded from authentication

        Args:
            path: Request URL path

        Returns:
            True if path is excluded, False otherwise
        """
        return any(path.startswith(excluded) for excluded in self.excluded_paths)

    def _is_no_auth_path(self, path: str) -> bool:
        """
        Check if the request path is in the no-auth list

        Args:
            path: Request URL path

        Returns:
            True if path requires no authentication, False otherwise
        """
        return any(path.startswith(no_auth) for no_auth in self.no_auth_paths)

    async def _authenticate_request(self, request: Request) -> Dict[str, Any]:
        """
        Extract and validate JWT token from request

        Args:
            request: FastAPI request object

        Returns:
            User information dictionary

        Raises:
            HTTPException: If authentication fails
        """
        # Extract Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header missing",
            )

        # Validate Bearer token format
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format. Expected 'Bearer <token>'",
            )

        # Extract token
        token = auth_header[7:]  # Remove 'Bearer ' prefix

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT token missing"
            )

        # Validate token using JWT service
        if not self.jwt_service:
            logger.error("JWT auth service not initialized")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication service unavailable",
            )

        try:
            user_info = self.jwt_service.get_user_info(token)
            return user_info
        except HTTPException:
            # Re-raise HTTP exceptions from JWT service
            raise
        except Exception as e:
            logger.error(f"Token validation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

    def _check_role_access(
        self, path: str, method: str, user_info: Dict[str, Any]
    ) -> None:
        """
        Check if user has required role for the requested path using hierarchical access control

        Args:
            path: Request URL path
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            user_info: User information from JWT token

        Raises:
            HTTPException: If user lacks required permissions
        """

        # Extract roles from token payload if not in roles array
        token_payload = user_info.get("token_payload", {})
        if "roles" in token_payload:
            user_roles = token_payload.get("roles", [UserRole.USER.value])
        else:
            user_roles = [UserRole.USER.value]

        # Check if user has any valid role
        valid_roles = [
            UserRole.USER.value,
            UserRole.ADMIN.value,
            UserRole.SUPER_ADMIN.value,
        ]
        if not any(role in user_roles for role in valid_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Valid user role required"
            )

        # Determine user's highest role level
        is_super_admin = UserRole.SUPER_ADMIN.value in user_roles
        is_admin = UserRole.ADMIN.value in user_roles or is_super_admin
        is_user = UserRole.USER.value in user_roles or is_admin

        # Check Super Admin only paths
        if any(path.startswith(super_path) for super_path in self.super_admin_paths):
            if not is_super_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Super Admin access required",
                )
            logger.debug(f"Super Admin access granted for {method} {path}")
            return

        # Check Admin paths (accessible by admin and super admin)
        if any(path.startswith(admin_path) for admin_path in self.admin_paths):
            if not is_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin access required",
                )
            logger.debug(f"Admin access granted for {method} {path}")
            return

        # Check User paths (accessible by user, admin, and super admin)
        if any(path.startswith(user_path) for user_path in self.user_paths):
            if not is_user:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="User access required"
                )
            logger.debug(f"User access granted for {method} {path}")
            return

        # For any other protected paths, require at least user role
        if not is_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Authentication required"
            )

        logger.debug(
            f"Default access granted for {method} {path} with roles: {user_roles}"
        )


def get_current_user_from_request(request: Request) -> Dict[str, Any]:
    """
    Helper function to get current user from request state

    Args:
        request: FastAPI request object

    Returns:
        Current user information

    Raises:
        HTTPException: If user not found in request state
    """
    if not hasattr(request.state, "current_user"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not authenticated"
        )

    return request.state.current_user
