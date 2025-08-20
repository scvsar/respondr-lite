<<<<<<< HEAD
"""User authentication and profile endpoints."""

from fastapi import APIRouter, Request
from typing import List, Optional

from ..config import allowed_email_domains, DEBUG_LOG_HEADERS, ALLOW_LOCAL_AUTH_BYPASS, is_testing
import logging
from urllib.parse import quote
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def is_email_domain_allowed(email: str) -> bool:
    """Check if email domain is in allowed domains list."""
    try:
        if not email or "@" not in email:
            return False
        domain = email.split("@")[-1].strip().lower()
        return domain in [d.lower() for d in allowed_email_domains]
    except Exception:
        return False


@router.get("/api/user")
def get_user_info(request: Request) -> JSONResponse:
    """Get user info from OAuth2 Proxy headers."""
    if DEBUG_LOG_HEADERS:
        logger.debug("=== DEBUG: All headers received ===")
        for header_name, header_value in request.headers.items():
            if header_name.lower().startswith('x-'):
                logger.debug(f"Header: {header_name} = {header_value}")
        logger.debug("=== END DEBUG ===")

    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
    )
    user_name = (
        request.headers.get("X-Auth-Request-Preferred-Username")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-preferred-username")
    )
    user_groups = request.headers.get("X-Auth-Request-Groups", "").split(",") if request.headers.get("X-Auth-Request-Groups") else []

    if not user_email:
        user_email = request.headers.get("X-User")
    if not user_name:
        user_name = request.headers.get("X-Preferred-Username") or request.headers.get("X-User-Name")
    if not user_groups:
        user_groups = request.headers.get("X-User-Groups", "").split(",") if request.headers.get("X-User-Groups") else []

    if user_email or user_name:
        if user_email and not is_email_domain_allowed(user_email):
            logger.warning(f"Access denied for user {user_email}: domain not in allowed list")
            return JSONResponse(status_code=403, content={
                "authenticated": False,
                "error": "Access denied",
                "message": f"Your domain is not authorized to access this application. Allowed domains: {', '.join(allowed_email_domains)}",
                "logout_url": f"/oauth2/sign_out?rd={quote('/', safe='')}",
            })
        authenticated = True
        display_name = user_name or user_email
        email = user_email
    else:
        if ALLOW_LOCAL_AUTH_BYPASS and not is_testing:
            authenticated = True
            display_name = "Local Dev User"
            email = "dev@local"
            user_groups = []
        else:
            authenticated = False
            display_name = None
            email = None
            user_groups = []

    # Clean up groups list
    groups = [g.strip() for g in user_groups if g.strip()] if user_groups else []

    return JSONResponse(content={
        "authenticated": authenticated,
        "email": email,
        "name": display_name,
        "groups": groups,
        "logout_url": f"/oauth2/sign_out?rd={quote('/', safe='')}",
    })
=======
from urllib.parse import quote
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..config import ALLOW_LOCAL_AUTH_BYPASS

router = APIRouter()

allowed_email_domains = ["scvsar.org", "rtreit.com"]

def is_email_domain_allowed(email: str) -> bool:
    try:
        domain = email.split("@")[1].lower()
        return domain in allowed_email_domains
    except Exception:
        return False

@router.get("/api/user")
async def get_user_info(request: Request) -> JSONResponse:
    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
        or request.headers.get("X-User")
    )
    user_name = (
        request.headers.get("X-Auth-Request-Preferred-Username")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-preferred-username")
        or request.headers.get("X-Preferred-Username")
        or request.headers.get("X-User-Name")
    )
    user_groups = (
        request.headers.get("X-Auth-Request-Groups")
        or request.headers.get("X-User-Groups")
        or ""
    ).split(",")

    if user_email and not is_email_domain_allowed(user_email):
        return JSONResponse(status_code=403, content={
            "authenticated": False,
            "error": "Access denied",
            "message": "Your domain is not authorized to access this application.",
            "logout_url": f"/oauth2/sign_out?rd={quote('/', safe='')}",
        })

    return JSONResponse(content={
        "authenticated": bool(user_email or ALLOW_LOCAL_AUTH_BYPASS),
        "email": user_email,
        "name": user_name or user_email,
        "groups": [g.strip() for g in user_groups if g.strip()],
        "is_admin": False,
        "logout_url": f"/oauth2/sign_out?rd={quote('/', safe='')}",
    })
>>>>>>> ef84adee5db2588b7c1441dfc10679fb2b09f3e0
