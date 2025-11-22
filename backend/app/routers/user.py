"""User authentication and profile endpoints."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from typing import List, Optional
from urllib.parse import quote
import logging

from ..config import (
    allowed_email_domains, allowed_admin_users, 
    FORCE_GEOCITIES_MODE, ENABLE_GEOCITIES_TOGGLE, INACTIVITY_TIMEOUT_MINUTES,
    ALLOW_LOCAL_AUTH_BYPASS, LOCAL_BYPASS_IS_ADMIN, ENABLE_LOCAL_AUTH, is_testing
)
from ..auth.dependencies import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/api/user")
def get_user_info(user: dict = Depends(require_auth)) -> JSONResponse:
    """Get user info from the validated JWT token."""
    
    # Extract info from token payload
    email = user.get("preferred_username") or user.get("email")
    name = user.get("name") or user.get("display_name") or email
    is_admin = user.get("is_admin", False)
    auth_type = user.get("auth_type", "entra") # Default to entra if not specified (local has it)
    
    # If Entra, check admin status again (though require_admin does it, require_auth doesn't)
    if auth_type != "local" and email:
         if email.lower() in [u.lower() for u in allowed_admin_users]:
             is_admin = True

    return JSONResponse(content={
        "authenticated": True,
        "email": email,
        "name": name,
        "groups": user.get("groups", []),
        "is_admin": is_admin,
        "auth_type": auth_type,
        "organization": user.get("organization", ""),
        # Logout URL is handled by frontend now, but we can provide a hint or remove it
        "logout_url": "/.auth/logout" if auth_type != "local" else None
    })


@router.get("/api/config")
def get_client_config(_: dict = Depends(require_auth)) -> JSONResponse:
    """Get configuration settings for the frontend."""
    config = {
        "geocities": {
            "force_mode": FORCE_GEOCITIES_MODE,
            "enable_toggle": ENABLE_GEOCITIES_TOGGLE
        },
        "inactivity": {
            "timeout_minutes": INACTIVITY_TIMEOUT_MINUTES
        },
        "debug": {
            "allow_local_auth_bypass": ALLOW_LOCAL_AUTH_BYPASS,
            "local_bypass_is_admin": LOCAL_BYPASS_IS_ADMIN,
            "enable_local_auth": ENABLE_LOCAL_AUTH,
            "is_testing": is_testing,
        }
    }
    return JSONResponse(content=config)

