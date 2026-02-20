import logging
import os
import jwt
from typing import Optional, Union
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWKClient
from ..config import LOCAL_AUTH_SECRET_KEY, allowed_admin_users, is_testing
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
    logger.warning("API audience not set; Entra validation will skip audience check")

JWKS_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

jwks_client = PyJWKClient(JWKS_URL) if TENANT_ID else None


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


def _extract_unverified_claim(token_value: str, claim: str) -> Optional[Union[str, list]]:
    try:
        payload = jwt.decode(
            token_value,
            options={"verify_signature": False, "verify_aud": False, "verify_iss": False},
            algorithms=["RS256", "HS256"],
        )
        return payload.get(claim)
    except Exception as decode_err:
        logger.debug("Unable to decode token for %s claim: %s", claim, decode_err)
        return None


def require_auth(request: Request, token: Optional[str] = Depends(oauth2_scheme)):
    print("🟢 require_auth called")
    logger.info("require_auth called")
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token_value: Optional[str] = token if token else extract_session_token_from_request(request)
    if not token_value:
        print("🔴 No token found in require_auth")
        logger.warning("No token found in require_auth")
        raise credentials_exception

    try:
        # First, try to decode header to see alg
        unverified_header = jwt.get_unverified_header(token_value)
        alg = unverified_header.get("alg")
        print(f"🔑 Token algorithm: {alg}")
        logger.info(f"Token algorithm: {alg}")

        raw_audience = _extract_unverified_claim(token_value, "aud")
        normalized_raw_audience: Optional[str] = None
        if isinstance(raw_audience, (list, tuple)):
            normalized_raw_audience = _normalize_audience(raw_audience[0]) if raw_audience else None
        else:
            normalized_raw_audience = _normalize_audience(raw_audience)
        
        if alg == "HS256":
            # Local Auth
            if not LOCAL_AUTH_SECRET_KEY:
                 raise HTTPException(status_code=500, detail="Local auth not configured")
                 
            try:
                payload = jwt.decode(token_value, LOCAL_AUTH_SECRET_KEY, algorithms=["HS256"])
                # Allow 'local' issuer or no issuer
                if payload.get("iss") and payload.get("iss") != "local":
                    raise credentials_exception
                return payload
            except jwt.ExpiredSignatureError:
                raise HTTPException(status_code=401, detail="Token expired")
            except jwt.InvalidTokenError as e:
                logger.warning("Local auth token validation failed: %s", e)
                raise credentials_exception
                
        elif alg == "RS256":
            print("🔐 RS256 token detected")
            logger.info("RS256 token detected")
            # Entra ID
            if not jwks_client:
                 print("❌ JWKS client not configured")
                 raise HTTPException(status_code=500, detail="Entra ID not configured")

            try:
                print(f"🎯 Validating token with audience: {API_AUDIENCE}")
                logger.info(f"Validating token with audience: {API_AUDIENCE}")
                signing_key = jwks_client.get_signing_key_from_jwt(token_value)
                
                # We need to know the audience. 
                # If API_AUDIENCE is not set, we might skip audience validation or try to infer.
                # But PyJWT requires audience if it's in the token.
                # For multi-tenant apps, we should disable issuer verification or validate it manually
                options = {
                    "verify_aud": bool(API_AUDIENCE),
                    "verify_iss": False,
                }
                audiences = []
                if API_AUDIENCE:
                    audiences.append(API_AUDIENCE)
                    if API_AUDIENCE.startswith("api://"):
                        bare = API_AUDIENCE[len("api://"):]
                        if bare:
                            audiences.append(bare)
                if AAD_CLIENT_ID and AAD_CLIENT_ID not in audiences:
                    audiences.append(AAD_CLIENT_ID)

                audience_param = audiences if len(audiences) > 1 else (audiences[0] if audiences else None)
                logger.debug(
                    "Validating Entra token using audiences=%s (verify_aud=%s)",
                    audiences if audiences else ["<none>"],
                    options["verify_aud"],
                )
                
                payload = jwt.decode(
                    token_value,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=audience_param,
                    options=options
                )
                
                print(f"✅ Token validated successfully for {payload.get('preferred_username', 'unknown')}")
                logger.info(f"Token validated successfully for {payload.get('preferred_username', 'unknown')}")
                
                # Enforce domain restrictions
                email = _extract_user_email(payload)
                if not email:
                    logger.warning("No email-like claim found in token; claims keys=%s", list(payload.keys()))
                
                allowed_domains = [d.strip() for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()]
                if email and allowed_domains:
                    # Case-insensitive check
                    email_lower = email.lower()
                    if not any(email_lower.endswith("@" + d.lower()) for d in allowed_domains):
                        logger.warning("Access denied for %s: Domain not in allowed list", email)
                        raise HTTPException(status_code=403, detail="Email domain not allowed")
                
                return payload
            except HTTPException:
                # Re-raise HTTP exceptions (like 403 for domain restrictions)
                print("❌ HTTP exception during validation")
                raise
            except Exception as e:
                print(f"❌ Token validation failed: {type(e).__name__}: {str(e)}")
                logger.error(f"Token validation failed: {type(e).__name__}: {str(e)}")
                actual_aud = "unknown"
                try:
                    unverified_payload = jwt.decode(
                        token_value,
                        options={"verify_signature": False, "verify_aud": False, "verify_iss": False},
                        algorithms=["RS256"],
                    )
                    actual_aud = unverified_payload.get("aud", actual_aud)
                except Exception as inspect_error:
                    logger.debug("Could not decode token for diagnostics: %s", inspect_error)

                logger.warning(
                    "Entra token validation failed (expected aud=%s, received aud=%s): %s",
                    API_AUDIENCE,
                    actual_aud,
                    str(e),
                )
                raise credentials_exception
        else:
            raise credentials_exception
            
    except Exception as e:
        # print(f"Auth error: {e}")
        raise credentials_exception

def require_admin(user: dict = Depends(require_auth)):
    if is_testing:
        return user
        
    # Check if user is admin
    # Local auth has "is_admin" in payload
    if user.get("auth_type") == "local":
        local_is_admin = bool(user.get("is_admin"))
        local_email = (user.get("email") or "").strip().lower()
        email_allowlisted = local_email in [u.lower() for u in allowed_admin_users]
        if not (local_is_admin or email_allowlisted):
            raise HTTPException(status_code=403, detail="Admin privileges required")
        return user
        
    # Entra ID
    email = _extract_user_email(user)
    if not email:
        logger.warning("Admin check failed: no email-like claim present. keys=%s", list(user.keys()))
        raise HTTPException(status_code=403, detail="Email required for admin check")
        
    if email.lower() not in [u.lower() for u in allowed_admin_users]:
        raise HTTPException(status_code=403, detail="Admin privileges required")
        
    return user
