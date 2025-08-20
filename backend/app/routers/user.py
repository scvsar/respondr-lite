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
