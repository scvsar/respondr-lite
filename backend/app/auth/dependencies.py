import os
import jwt
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWKClient
from ..config import LOCAL_AUTH_SECRET_KEY, allowed_admin_users, is_testing
from ..local_auth import extract_session_token_from_request

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

# Entra ID Config
TENANT_ID = os.getenv("REACT_APP_AAD_TENANT_ID") or os.getenv("AZURE_TENANT_ID")
API_AUDIENCE = os.getenv("API_AUDIENCE") or os.getenv("REACT_APP_AAD_CLIENT_ID")

JWKS_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

jwks_client = PyJWKClient(JWKS_URL) if TENANT_ID else None

def require_auth(request: Request, token: Optional[str] = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token_value: Optional[str] = token if token else extract_session_token_from_request(request)
    if not token_value:
        raise credentials_exception

    try:
        # First, try to decode header to see alg
        unverified_header = jwt.get_unverified_header(token_value)
        alg = unverified_header.get("alg")
        
        if alg == "HS256":
            # Local Auth
            if not LOCAL_AUTH_SECRET_KEY:
                 raise HTTPException(status_code=500, detail="Local auth not configured")
                 
            try:
                payload = jwt.decode(token_value, LOCAL_AUTH_SECRET_KEY, algorithms=["HS256"])
                if payload.get("iss") not in ("local", None):
                    raise credentials_exception
                return payload
            except jwt.ExpiredSignatureError:
                raise HTTPException(status_code=401, detail="Token expired")
            except jwt.InvalidTokenError:
                raise credentials_exception
                
        elif alg == "RS256":
            # Entra ID
            if not jwks_client:
                 raise HTTPException(status_code=500, detail="Entra ID not configured")

            try:
                signing_key = jwks_client.get_signing_key_from_jwt(token_value)
                
                # We need to know the audience. 
                # If API_AUDIENCE is not set, we might skip audience validation or try to infer.
                # But PyJWT requires audience if it's in the token.
                # For multi-tenant apps, we should disable issuer verification or validate it manually
                options = {
                    "verify_aud": bool(API_AUDIENCE),
                    "verify_iss": False 
                }
                
                payload = jwt.decode(
                    token_value,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=API_AUDIENCE,
                    options=options
                )
                
                # Enforce domain restrictions
                email = payload.get("preferred_username") or payload.get("email")
                if not email:
                     # Some tokens might not have email, but for this app we expect it.
                     pass 
                
                allowed_domains = os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",")
                if email and allowed_domains and allowed_domains != [""]:
                    if not any(email.endswith("@" + d.strip()) for d in allowed_domains if d.strip()):
                        raise HTTPException(status_code=403, detail="Email domain not allowed")
                
                return payload
            except Exception as e:
                print(f"Entra validation error: {e}")
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
        if not user.get("is_admin"):
             raise HTTPException(status_code=403, detail="Admin privileges required")
        return user
        
    # Entra ID
    email = user.get("preferred_username") or user.get("email")
    if not email:
        raise HTTPException(status_code=403, detail="Email required for admin check")
        
    if email.lower() not in [u.lower() for u in allowed_admin_users]:
        raise HTTPException(status_code=403, detail="Admin privileges required")
        
    return user
