"""Local authentication endpoints for external users."""

import logging
import os
from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from ..config import ENABLE_LOCAL_AUTH, allowed_admin_users, is_testing
from ..local_auth import (
    verify_local_user, create_session_token,
    create_local_user, update_local_user_password, list_local_users, get_local_user, delete_local_user
)
from ..auth.dependencies import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str  # Changed from EmailStr to avoid email-validator dependency
    display_name: str
    organization: str = ""
    is_admin: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class AdminPasswordResetRequest(BaseModel):
    username: str
    new_password: str


def get_current_user_from_token(request: Request) -> Optional[dict]:
    """Extract and verify current user from session token."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return None
    
    from ..local_auth import extract_session_token_from_request, verify_session_token
    
    token = extract_session_token_from_request(request)
    if not token:
        return None
    
    return verify_session_token(token)



@router.post("/api/auth/local/login")
async def local_login(login_request: LoginRequest):
    """Login with username/password for local accounts."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Local authentication is not enabled"}
        )
    
    try:
        user = await verify_local_user(login_request.username, login_request.password)
        if user:
            token = create_session_token(user)
            
            # Create response with token in both header and cookie
            response = JSONResponse(content={
                "success": True,
                "token": token,
                "user": {
                    "username": user.username,
                    "email": user.email,
                    "display_name": user.display_name,
                    "is_admin": user.is_admin,
                    "organization": user.organization,
                    "auth_type": "local"
                }
            })
            
            # Determine cookie security
            # If using local storage emulator, assume local dev (HTTP)
            storage_conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
            is_local_dev = (
                storage_conn.startswith("UseDevelopmentStorage=true") or 
                "127.0.0.1" in storage_conn or 
                "localhost" in storage_conn or
                "devstoreaccount1" in storage_conn
            )

            # Set secure HTTP-only cookie for browser-based requests
            max_age_seconds = int(timedelta(hours=24).total_seconds())

            response.set_cookie(
                key="session_token",
                value=token,
                httponly=True,
                secure=not is_local_dev,
                samesite="lax",
                max_age=max_age_seconds
            )
            
            logger.info(f"Successful local login: {user.username} ({user.email})")
            return response
        else:
            logger.warning(f"Failed local login attempt: {login_request.username}")
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Invalid username or password"}
            )
            
    except Exception as e:
        logger.error(f"Error in local login: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Login failed"}
        )


@router.post("/api/auth/local/logout")
async def local_logout():
    """Logout from local session."""
    response = JSONResponse(content={"success": True, "message": "Logged out"})
    response.delete_cookie("session_token")
    return response


@router.get("/api/auth/local/me")
async def get_current_local_user(request: Request):
    """Get current local user info from session token."""
    user = get_current_user_from_token(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return {
        "authenticated": True,
        "username": user["username"],
        "email": user["email"],
        "display_name": user["display_name"],
        "is_admin": user["is_admin"],
        "organization": user["organization"],
        "auth_type": user["auth_type"]
    }


@router.post("/api/auth/local/change-password")
async def change_password(request: Request, password_request: PasswordChangeRequest):
    """Change current user's password."""
    user = get_current_user_from_token(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Verify current password
    current_user = await verify_local_user(user["username"], password_request.current_password)
    if not current_user:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    # Update password
    success = await update_local_user_password(user["username"], password_request.new_password)
    if success:
        logger.info(f"Password changed for local user: {user['username']}")
        return {"success": True, "message": "Password changed successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to change password")


# Admin-only endpoints
@router.post("/api/auth/local/admin/create-user")
async def admin_create_user(
    create_request: CreateUserRequest,
    _: bool = Depends(require_admin)
):
    """Create a new local user (admin only)."""
    success = await create_local_user(
        username=create_request.username,
        password=create_request.password,
        email=create_request.email,
        display_name=create_request.display_name,
        is_admin=create_request.is_admin,
        organization=create_request.organization
    )
    
    if success:
        logger.info(f"Admin created local user: {create_request.username}")
        return {
            "success": True, 
            "message": f"User '{create_request.username}' created successfully"
        }
    else:
        raise HTTPException(status_code=400, detail="Failed to create user (may already exist)")


@router.post("/api/auth/local/admin/reset-password")
async def admin_reset_password(
    reset_request: AdminPasswordResetRequest,
    _: bool = Depends(require_admin)
):
    """Reset a user's password (admin only)."""
    success = await update_local_user_password(reset_request.username, reset_request.new_password)
    
    if success:
        logger.info(f"Admin reset password for: {reset_request.username}")
        return {
            "success": True,
            "message": f"Password reset for user '{reset_request.username}'"
        }
    else:
        raise HTTPException(status_code=404, detail="User not found")


@router.get("/api/auth/local/admin/users")
async def admin_list_users(_: bool = Depends(require_admin)):
    """List all local users (admin only)."""
    users = await list_local_users()
    
    return {
        "users": [
            {
                "username": user.username,
                "email": user.email,
                "display_name": user.display_name,
                "is_admin": user.is_admin,
                "organization": user.organization,
                "created_at": user.created_at.isoformat() if user.created_at else None
            }
            for user in users
        ]
    }


@router.delete("/api/auth/local/admin/users/{username}")
async def admin_delete_user(username: str, _: bool = Depends(require_admin)):
    """Delete a local user (admin only)."""
    success = await delete_local_user(username)
    
    if success:
        return {"success": True, "message": f"User '{username}' deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="User not found or failed to delete")


@router.get("/api/auth/local/enabled")
async def check_local_auth_enabled():
    """Check if local authentication is enabled."""
    return {
        "enabled": ENABLE_LOCAL_AUTH or is_testing,
        "auth_type": "local"
    }