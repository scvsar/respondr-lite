"""Responders API endpoints for managing SAR response messages."""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import APP_TZ, GROUP_ID_TO_TEAM, allowed_email_domains, allowed_admin_users, ALLOW_LOCAL_AUTH_BYPASS, LOCAL_BYPASS_IS_ADMIN, is_testing
from ..utils import parse_datetime_like, compute_eta_fields
from ..storage import (
    get_messages, add_message, update_message, delete_message, 
    get_deleted_messages, undelete_message, permanently_delete_message,
    clear_all_messages, clear_all_deleted_messages, bulk_delete_messages,
    get_storage_info
)

logger = logging.getLogger(__name__)
router = APIRouter()


def is_email_domain_allowed(email: str) -> bool:
    """Check if email domain is in allowed domains list."""
    if is_testing and email.endswith("@example.com"):
        return True
    try:
        if not email or "@" not in email:
            return False
        domain = email.split("@")[-1].strip().lower()
        return domain in [d.lower() for d in allowed_email_domains]
    except Exception:
        return False


def is_admin(email: Optional[str]) -> bool:
    """Check if user email is in admin users list."""
    if is_testing:
        return True
    if ALLOW_LOCAL_AUTH_BYPASS and LOCAL_BYPASS_IS_ADMIN:
        return True
    if not email:
        return False
    try:
        return email.strip().lower() in [u.lower() for u in allowed_admin_users]
    except Exception:
        return False


def require_admin_access(request: Request) -> bool:
    """Dependency that requires admin access for the endpoint."""
    # During testing, bypass authentication entirely
    if is_testing:
        return True
        
    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
        or request.headers.get("X-User")
    )
    
    if not user_email:
        if ALLOW_LOCAL_AUTH_BYPASS:
            # Local development bypass
            return True
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if not is_email_domain_allowed(user_email):
        raise HTTPException(status_code=403, detail="Access denied: domain not authorized")
    
    if not is_admin(user_email):
        raise HTTPException(status_code=403, detail="Access denied: admin privileges required")
    
    return True


def require_authenticated_access(request: Request) -> bool:
    """Dependency that requires authenticated access (any valid user)."""
    # During testing, bypass authentication entirely
    if is_testing:
        return True
        
    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
        or request.headers.get("X-User")
    )
    
    if not user_email:
        if ALLOW_LOCAL_AUTH_BYPASS:
            # Local development bypass
            return True
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if not is_email_domain_allowed(user_email):
        raise HTTPException(status_code=403, detail="Access denied: domain not authorized")
    
    return True


class ResponderUpdate(BaseModel):
    name: Optional[str] = None
    vehicle: Optional[str] = None
    eta: Optional[str] = None
    eta_timestamp: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    ids: List[str]  # Frontend sends 'ids', not 'message_ids'


class UndeleteRequest(BaseModel):
    message_id: str


# Remove in-memory storage - using storage layer now


@router.get("/api/responders")
async def get_responders(_: bool = Depends(require_authenticated_access)):
    """Get all active responder messages."""
    try:
        messages = get_messages()
        return messages
    except Exception as e:
        logger.error(f"Failed to get responders: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve responders")


@router.get("/api/current-status")
async def get_current_status(_: bool = Depends(require_authenticated_access)):
    """Get current status per person (latest message per person with priority logic)."""
    try:
        messages = get_messages()
        
        def _coerce_dt(s: Optional[str]) -> datetime:
            """Coerce various timestamp strings to a timezone-aware UTC datetime for stable sorting."""
            if not s:
                return datetime.min.replace(tzinfo=timezone.utc)
            try:
                return datetime.fromisoformat(str(s).replace('Z', '+00:00')).astimezone(timezone.utc)
            except Exception:
                try:
                    # Legacy testing format: naive local time -> assume APP_TZ and convert to UTC
                    dt_local = datetime.strptime(str(s), '%Y-%m-%d %H:%M:%S').replace(tzinfo=APP_TZ)
                    return dt_local.astimezone(timezone.utc)
                except Exception:
                    return datetime.min.replace(tzinfo=timezone.utc)
        
        latest_by_person = {}
        sorted_messages = sorted(messages, key=lambda x: _coerce_dt(x.get('timestamp_utc') or x.get('timestamp')))
        
        for msg in sorted_messages:
            name = (msg.get('name') or '').strip()
            if not name:
                continue
                
            arrival_status = msg.get('arrival_status', 'Unknown')
            eta = msg.get('eta', 'Unknown')
            text = (msg.get('text') or '').lower()
            
            # Priority logic from monolith
            priority = 0
            if arrival_status == 'Cancelled' or "can't make it" in text or 'cannot make it' in text:
                priority = 100
            elif arrival_status == 'Not Responding':
                priority = 10
            elif arrival_status == 'Responding' and eta != 'Unknown':
                priority = 80
            elif arrival_status == 'Responding':
                priority = 60
            elif eta != 'Unknown':
                priority = 70
            elif arrival_status == 'Available':
                priority = 40
            elif arrival_status == 'Informational':
                priority = 15
            else:
                priority = 20
            
            current_entry = latest_by_person.get(name)
            if current_entry is None:
                latest_by_person[name] = dict(msg)
                latest_by_person[name]['_priority'] = priority
            else:
                current_ts = _coerce_dt(current_entry.get('timestamp_utc') or current_entry.get('timestamp'))
                new_ts = _coerce_dt(msg.get('timestamp_utc') or msg.get('timestamp'))
                if new_ts >= current_ts:
                    latest_by_person[name] = dict(msg)
                    latest_by_person[name]['_priority'] = priority
                elif new_ts == current_ts and priority > current_entry.get('_priority', 0):
                    latest_by_person[name] = dict(msg)
                    latest_by_person[name]['_priority'] = priority
        
        # Convert to result list and remove priority field
        result = []
        for person_data in latest_by_person.values():
            person_data.pop('_priority', None)
            result.append(person_data)
        
        # Sort by timestamp descending
        result.sort(key=lambda x: _coerce_dt(x.get('timestamp_utc') or x.get('timestamp')), reverse=True)
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get current status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get status")


@router.post("/api/responders")
async def create_responder(data: Dict[str, Any], _: bool = Depends(require_admin_access)):
    """Create a new responder message manually."""
    try:
        # Process the input data
        timestamp = parse_datetime_like(data.get("timestamp")) or datetime.now(APP_TZ)
        
        # Compute ETA fields if provided
        eta_fields = {}
        if data.get("eta") or data.get("eta_timestamp"):
            eta_ts = parse_datetime_like(data.get("eta_timestamp")) if data.get("eta_timestamp") else None
            eta_fields = compute_eta_fields(data.get("eta"), eta_ts, timestamp)
        
        # Generate a unique ID
        import uuid
        msg_id = str(uuid.uuid4())
        
        # Determine team from group_id
        group_id = data.get("group_id", "manual")
        team = GROUP_ID_TO_TEAM.get(group_id, "Manual") if group_id != "manual" else "Manual"
        
        # Create message
        message = {
            "id": msg_id,
            "name": data.get("name", "Unknown"),
            "text": data.get("text", ""),
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "vehicle": data.get("vehicle", "Unknown"),
            "eta": eta_fields.get("eta", "Unknown"),
            "eta_timestamp": eta_fields.get("eta_timestamp"),
            "eta_timestamp_utc": eta_fields.get("eta_timestamp_utc"),
            "minutes_until_arrival": eta_fields.get("minutes_until_arrival"),
            "arrival_status": eta_fields.get("arrival_status", "Unknown"),
            "raw_status": data.get("status", "Unknown"),
            "status_source": "Manual",
            "status_confidence": 1.0,
            "team": team,
            "group_id": group_id,
            "created_at": int(timestamp.timestamp()),
        }
        
        # Store in storage layer
        add_message(message)
        
        return {"status": "created", "message": message}
        
    except Exception as e:
        logger.error(f"Failed to create responder: {e}")
        raise HTTPException(status_code=500, detail="Failed to create responder")


@router.put("/api/responders/{msg_id}")
async def update_responder(msg_id: str, update: ResponderUpdate, _: bool = Depends(require_admin_access)):
    """Update an existing responder message."""
    try:
        # Prepare updates
        updates = {}
        if update.name is not None:
            updates["name"] = update.name
        if update.vehicle is not None:
            updates["vehicle"] = update.vehicle
        
        # Handle ETA updates
        if update.eta is not None or update.eta_timestamp is not None:
            # Get current message to use as base for ETA computation
            messages = get_messages()
            current_msg = None
            for msg in messages:
                if msg.get("id") == msg_id:
                    current_msg = msg
                    break
            
            if current_msg:
                base_time = parse_datetime_like(current_msg["timestamp"]) or datetime.now(APP_TZ)
                eta_ts = parse_datetime_like(update.eta_timestamp) if update.eta_timestamp else None
                eta_fields = compute_eta_fields(update.eta, eta_ts, base_time)
                updates.update(eta_fields)
        
        # Update in storage
        success = update_message(msg_id, updates)
        if not success:
            raise HTTPException(status_code=404, detail="Message not found")
        
        # Get updated message to return
        messages = get_messages()
        for msg in messages:
            if msg.get("id") == msg_id:
                return {"status": "updated", "message": msg}
        
        # Shouldn't reach here if update succeeded
        raise HTTPException(status_code=404, detail="Message not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update responder: {e}")
        raise HTTPException(status_code=500, detail="Failed to update responder")


@router.delete("/api/responders/{msg_id}")
async def delete_responder(msg_id: str, _: bool = Depends(require_admin_access)):
    """Soft delete a responder message."""
    try:
        success = delete_message(msg_id)
        if not success:
            raise HTTPException(status_code=404, detail="Message not found")
        
        return {"status": "deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete responder: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete responder")


@router.post("/api/responders/bulk-delete")
async def bulk_delete_responders(request: BulkDeleteRequest, _: bool = Depends(require_admin_access)):
    """Bulk delete multiple responder messages."""
    try:
        deleted_count = bulk_delete_messages(request.ids)
        return {"status": "deleted", "count": deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to bulk delete: {e}")
        raise HTTPException(status_code=500, detail="Failed to bulk delete")


@router.post("/api/clear-all")
async def clear_all_responders(_: bool = Depends(require_admin_access)):
    """Clear all active responders (soft delete)."""
    try:
        deleted_count = clear_all_messages()
        return {"status": "cleared", "count": deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to clear all: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear all")


@router.get("/api/deleted-responders")
async def get_deleted_responders(_: bool = Depends(require_admin_access)):
    """Get all soft-deleted responder messages."""
    try:
        return get_deleted_messages()
    except Exception as e:
        logger.error(f"Failed to get deleted responders: {e}")
        raise HTTPException(status_code=500, detail="Failed to get deleted responders")


@router.post("/api/deleted-responders/undelete")
async def undelete_responder(request: UndeleteRequest, _: bool = Depends(require_admin_access)):
    """Restore a deleted responder message."""
    try:
        success = undelete_message(request.message_id)
        if not success:
            raise HTTPException(status_code=404, detail="Deleted message not found")
        
        # Get the restored message to return
        messages = get_messages()
        for msg in messages:
            if msg.get("id") == request.message_id:
                return {"status": "restored", "message": msg}
        
        # This shouldn't happen if undelete succeeded
        return {"status": "restored"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to undelete: {e}")
        raise HTTPException(status_code=500, detail="Failed to undelete")


@router.delete("/api/deleted-responders/{msg_id}")
async def permanently_delete_responder(msg_id: str, _: bool = Depends(require_admin_access)):
    """Permanently delete a responder message."""
    try:
        success = permanently_delete_message(msg_id)
        if not success:
            raise HTTPException(status_code=404, detail="Deleted message not found")
        
        return {"status": "permanently_deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to permanently delete: {e}")
        raise HTTPException(status_code=500, detail="Failed to permanently delete")


@router.post("/api/deleted-responders/clear-all")
async def clear_all_deleted(_: bool = Depends(require_admin_access)):
    """Permanently delete all soft-deleted messages."""
    try:
        deleted_count = clear_all_deleted_messages()
        return {"status": "cleared", "count": deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to clear deleted: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear deleted")


@router.get("/api/storage-info")
async def get_storage_status():
    """Get current storage backend status and configuration."""
    try:
        storage_info = get_storage_info()
        return storage_info
        
    except Exception as e:
        logger.error(f"Failed to get storage info: {e}")
        raise HTTPException(status_code=500, detail="Failed to get storage info")
