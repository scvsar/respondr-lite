import logging
import os
import jwt
from typing import Optional
from uuid import UUID
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWKClient
from ..config import LOCAL_AUTH_SECRET_KEY, ENABLE_LOCAL_AUTH, allowed_admin_users, is_testing
from ..local_auth import extract_session_token_from_request

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

logger = logging.getLogger(__name__)

# Entra ID Config
TENANT_ID = os.getenv("REACT_APP_AAD_TENANT_ID") or os.getenv("AZURE_TENANT_ID")


def _normalize_audience(value: Optional[str]) -> Optional[str]:
    """Strip scope suffixes like /access_as_user from api:// audiences."""
    if not value:
        return None

    trimmed = value.strip()
    if not trimmed:
        return None

    if trimmed.startswith("api://"):
        without_scheme = trimmed[len("api://") :]
        # Keep only the GUID / app identifier portion before any scope segment
        parts = without_scheme.split("/", 1)
        return f"api://{parts[0]}" if parts and parts[0] else trimmed

    return trimmed


API_AUDIENCE = _normalize_audience(
    os.getenv("API_AUDIENCE")
    or os.getenv("REACT_APP_AAD_API_SCOPE")
    or os.getenv("REACT_APP_AAD_CLIENT_ID")
)

AAD_CLIENT_ID = (os.getenv("REACT_APP_AAD_CLIENT_ID") or "").strip()

if API_AUDIENCE:
    logger.info("Configured API audience: %s", API_AUDIENCE)
else:
    logger.warning("API audience not set; Entra authentication will reject tokens")

JWKS_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

jwks_client = PyJWKClient(JWKS_URL, timeout=10) if TENANT_ID else None
jwks_client_v1 = PyJWKClient(JWKS_URL.replace("/v2.0/", "/"), timeout=10) if TENANT_ID else None


def _extract_user_email(payload: dict) -> Optional[str]:
    """Extract the most reliable email/UPN-like identifier from token payload."""
    if not isinstance(payload, dict):
        return None

    for key in ("preferred_username", "email", "upn", "unique_name"):
        value = payload.get(key)
        if isinstance(value, str) and "@" in value:
            return value.strip().lower()

    emails = payload.get("emails")
    if isinstance(emails, (list, tuple)):
        for item in emails:
            if isinstance(item, str) and "@" in item:
                return item.strip().lower()

    return None


def require_auth(request: Request, token: Optional[str] = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token_value = token if isinstance(token, str) and token else extract_session_token_from_request(request)
    if not token_value:
        raise credentials_exception
    try:
        alg = jwt.get_unverified_header(token_value).get("alg")
        if alg == "HS256":
            if not ENABLE_LOCAL_AUTH or not LOCAL_AUTH_SECRET_KEY:
                raise credentials_exception
            payload = jwt.decode(
                token_value, LOCAL_AUTH_SECRET_KEY, algorithms=["HS256"], issuer="local",
                options={"require": ["iss", "exp", "username"]},
            )
            if not isinstance(payload.get("username"), str) or not payload["username"].strip():
                raise credentials_exception
            payload["auth_type"] = "local"
            return payload
        if alg != "RS256" or not jwks_client or not API_AUDIENCE:
            raise credentials_exception

        # Unverified values select validation parameters, never grant authorization.
        claims = jwt.decode(token_value, options={"verify_signature": False})
        tenant = str(UUID(claims.get("tid", "")))
        authority = (TENANT_ID or "").lower()
        if authority not in ("organizations", "common", "consumers") and str(UUID(authority)) != tenant:
            raise credentials_exception
        consumer_tenant = "9188040d-6c67-4c5b-b112-36a304b66dad"
        if authority == "organizations" and tenant == consumer_tenant:
            raise credentials_exception
        if authority == "consumers" and tenant != consumer_tenant:
            raise credentials_exception
        version = claims.get("ver")
        if version == "2.0":
            issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
            key_client = jwks_client
        elif version == "1.0":
            issuer = f"https://sts.windows.net/{tenant}/"
            key_client = jwks_client_v1
        else:
            raise credentials_exception
        signing_key = key_client.get_signing_key_from_jwt(token_value)
        key_issuer = signing_key._jwk_data.get("issuer", "").replace("{tenantid}", tenant)
        if key_issuer != issuer:
            raise credentials_exception
        audiences = [API_AUDIENCE]
        if API_AUDIENCE.startswith("api://"):
            audiences.append(API_AUDIENCE[len("api://"):])
        payload = jwt.decode(
            token_value, signing_key.key, algorithms=["RS256"], audience=audiences, issuer=issuer,
            options={"require": ["exp", "iss", "aud", "tid", "sub"]},
        )
        if "access_as_user" not in str(payload.get("scp") or "").split():
            raise credentials_exception
        email = _extract_user_email(payload)
        allowed_domains = [d.strip().lower() for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()]
        if allowed_domains and (not email or email.rsplit("@", 1)[-1] not in allowed_domains):
            raise HTTPException(status_code=403, detail="Email domain not allowed")
        payload["auth_type"] = "entra"
        return payload
    except HTTPException:
        raise
    except Exception:
        logger.warning("Token validation failed")
        raise credentials_exception


def is_admin_user(user: dict) -> bool:
    """Apply the shared local and Entra admin policy."""
    if user.get("auth_type") == "local" and user.get("is_admin") is True:
        return True
    email = _extract_user_email(user)
    return bool(email and email in {value.strip().lower() for value in allowed_admin_users})


def require_admin(user: dict = Depends(require_auth)):
    if is_testing:
        return user
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
