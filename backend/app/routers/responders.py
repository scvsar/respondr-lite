"""Responders API endpoints for managing SAR response messages."""

from ..responder_identity import attach_responder_keys
from ..message_policy import responder_messages
from ..message_time import parse_cutoff, messages_since
from ..request_log_reader import read_recent_request_logs
from starlette.concurrency import run_in_threadpool

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from pydantic import BaseModel, Field, ConfigDict

from ..config import APP_TZ, GROUP_ID_TO_TEAM, allowed_email_domains, allowed_admin_users, ALLOW_LOCAL_AUTH_BYPASS, LOCAL_BYPASS_IS_ADMIN, is_testing
from ..utils import parse_datetime_like, compute_eta_fields, coerce_datetime
from ..auth.dependencies import require_auth, require_admin
from ..storage import (
    get_messages, add_message, update_message, delete_message, 
    get_deleted_messages, undelete_message, permanently_delete_message,
    clear_all_messages, clear_all_deleted_messages, bulk_delete_messages,
    get_storage_info
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ResponderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1, pattern=r".*\S.*")
    text: Optional[str] = None
    team: Optional[str] = None
    group_id: Optional[str] = None
    timestamp: Optional[str] = None
    vehicle: Optional[str] = None
    eta: Optional[str] = None
    eta_timestamp: Optional[str] = None
    arrival_status: Optional[str] = None


class ResponderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, pattern=r".*\S.*")
    text: str = ""
    team: Optional[str] = None
    group_id: str = "manual"
    vehicle: str = "Unknown"
    timestamp: Optional[str] = None
    eta: Optional[str] = None
    eta_timestamp: Optional[str] = None
    arrival_status: Optional[str] = None
    status: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    ids: List[str]  # Frontend sends 'ids', not 'message_ids'


class UndeleteRequest(BaseModel):
    message_id: str


def _time_cutoff(since: str | None) -> datetime | None:
    try:
        return parse_cutoff(since)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid since timestamp") from None


@router.get("/api/responders")
async def get_responders(
    since: Optional[str] = Query(None, description="Filter messages since this time (ISO format)"),
    _: dict = Depends(require_auth)
) -> List[Dict[str, Any]]:
    """Get all active responder messages, optionally filtered by time."""
    cutoff = _time_cutoff(since)
    try:
        stored = await run_in_threadpool(get_messages)
        messages = messages_since(attach_responder_keys(responder_messages(stored)), cutoff)

        return messages
    except Exception as e:
        logger.error(f"Failed to get responders: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve responders")


@router.get("/api/current-status")
async def get_current_status(
    since: Optional[str] = Query(None, description="Filter messages since this time (ISO format)"),
    _: dict = Depends(require_auth)
) -> List[Dict[str, Any]]:
    """Get current status per person (latest message per person with priority logic)."""
    cutoff = _time_cutoff(since)
    try:
        stored = await run_in_threadpool(get_messages)
        messages = messages_since(attach_responder_keys(responder_messages(stored)), cutoff)

        _coerce_dt = coerce_datetime

        latest_by_person: Dict[str, Dict[str, Any]] = {}
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
            
            person_key = msg['responder_key']
            current_entry = latest_by_person.get(person_key)
            if current_entry is None:
                latest_by_person[person_key] = dict(msg)
                latest_by_person[person_key]['_priority'] = priority
            else:
                current_ts = _coerce_dt(current_entry.get('timestamp_utc') or current_entry.get('timestamp'))
                new_ts = _coerce_dt(msg.get('timestamp_utc') or msg.get('timestamp'))
                if new_ts > current_ts:
                    latest_by_person[person_key] = dict(msg)
                    latest_by_person[person_key]['_priority'] = priority
                elif new_ts == current_ts and priority > current_entry.get('_priority', 0):
                    latest_by_person[person_key] = dict(msg)
                    latest_by_person[person_key]['_priority'] = priority
        
        # Convert to result list and remove priority field
        result: List[Dict[str, Any]] = []
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
async def create_responder(data: ResponderCreate, _: dict = Depends(require_admin)) -> Dict[str, Any]:
    """Create a new responder message manually."""
    try:
        data = ResponderCreate.model_validate(data).model_dump()
        for field in ("timestamp", "eta_timestamp"):
            if data.get(field) and parse_datetime_like(data[field]) is None:
                raise HTTPException(status_code=400, detail="Invalid timestamp")
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
        team = data.get("team") or (GROUP_ID_TO_TEAM.get(group_id, "Manual") if group_id != "manual" else "Manual")

        status = data.get("arrival_status") or data.get("status") or eta_fields.get("arrival_status", "Unknown")
        if status not in ("Responding", "Available", "Informational", "Cancelled", "Not Responding", "Unknown", "Arrived"):
            raise HTTPException(status_code=400, detail="Invalid status")
        if status in ("Cancelled", "Not Responding"):
            eta_fields = {"eta": "Unknown", "eta_timestamp": None,
                          "eta_timestamp_utc": None, "minutes_until_arrival": None}

        # Create message
        message: Dict[str, Any] = {
            "id": msg_id,
            "name": data.get("name", "Unknown"),
            "text": data.get("text", ""),
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_utc": timestamp.astimezone(timezone.utc).isoformat(),
            "vehicle": data.get("vehicle", "Unknown"),
            "eta": eta_fields.get("eta", "Unknown"),
            "eta_timestamp": eta_fields.get("eta_timestamp"),
            "eta_timestamp_utc": eta_fields.get("eta_timestamp_utc"),
            "minutes_until_arrival": eta_fields.get("minutes_until_arrival"),
            "arrival_status": status,
            "raw_status": status,
            "status_source": "Manual",
            "status_confidence": 1.0,
            "team": team,
            "group_id": group_id,
            "created_at": int(timestamp.timestamp()),
        }
        
        # Store in storage layer
        if not await run_in_threadpool(add_message, message):
            raise RuntimeError("Failed to save responder")

        return {"status": "created", "message": message}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create responder: {e}")
        raise HTTPException(status_code=500, detail="Failed to create responder")


@router.put("/api/responders/{msg_id}")
async def update_responder(msg_id: str, update: ResponderUpdate, _: dict = Depends(require_admin)) -> Dict[str, Any]:
    """Update an existing responder message."""
    try:
        current_msg = next((m for m in await run_in_threadpool(get_messages) if m.get("id") == msg_id), None)
        if current_msg is None:
            raise HTTPException(status_code=404, detail="Message not found")
        # Prepare updates
        updates: Dict[str, Any] = {}
        if update.name is not None:
            updates["name"] = update.name
        if update.vehicle is not None:
            updates["vehicle"] = update.vehicle
        
        for field in ("text", "team", "group_id"):
            value = getattr(update, field)
            if value is not None:
                updates[field] = value
        if update.timestamp is not None:
            timestamp = parse_datetime_like(update.timestamp)
            if timestamp is None:
                raise HTTPException(status_code=400, detail="Invalid timestamp")
            updates.update(timestamp=timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                           timestamp_utc=timestamp.astimezone(timezone.utc).isoformat(),
                           created_at=int(timestamp.timestamp()))
        if current_msg.get("groupme_id"):
            for field in ("text", "name", "group_id", "created_at"):
                if field in updates and updates[field] != current_msg.get(field):
                    updates[f"original_{field}"] = current_msg.get(f"original_{field}", current_msg.get(field))

        # Handle arrival_status updates
        if update.arrival_status is not None:
            valid_statuses = ["Responding", "Available", "Informational", "Cancelled", "Not Responding", "Unknown"]
            if update.arrival_status in valid_statuses:
                updates["arrival_status"] = update.arrival_status
                updates["status_source"] = "Manual"  # Track that this was manually set
                updates["raw_status"] = update.arrival_status  # Update raw_status to match
                
                # Clear ETA fields if status is "Not Responding" or "Cancelled"
                if update.arrival_status in ["Not Responding", "Cancelled"]:
                    updates["eta"] = "Unknown"
                    updates["eta_timestamp_utc"] = None
                    updates["minutes_until_arrival"] = None
                    updates["eta_timestamp"] = None
                    updates["eta_lower"] = None
                    updates["eta_upper"] = None
            else:
                raise HTTPException(status_code=400, detail=f"Invalid status: {update.arrival_status}")
        
        # Handle ETA updates (skip if we're clearing due to status change)
        if (update.eta is not None or update.eta_timestamp is not None) and updates.get("arrival_status") not in ("Cancelled", "Not Responding"):
            # Get current message to use as base for ETA computation
            
            if current_msg:
                base_time = parse_datetime_like(updates.get("timestamp_utc") or current_msg.get("timestamp_utc") or current_msg.get("timestamp")) or datetime.now(APP_TZ)
                eta_ts = parse_datetime_like(update.eta_timestamp) if update.eta_timestamp else None
                eta_fields = compute_eta_fields(update.eta, eta_ts, base_time)
                if update.arrival_status is not None:
                    eta_fields.pop("arrival_status", None)
                updates.update(eta_fields)
        
        success = await run_in_threadpool(update_message, msg_id, updates)
        if not success:
            raise HTTPException(status_code=409, detail="Unable to update message. Refresh and retry.")

        # Get updated message to return
        messages = await run_in_threadpool(get_messages)
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
async def delete_responder(msg_id: str, _: dict = Depends(require_admin)) -> Dict[str, str]:
    """Soft delete a responder message."""
    try:
        success = await run_in_threadpool(delete_message, msg_id)
        if not success:
            raise HTTPException(status_code=404, detail="Message not found")
        
        return {"status": "deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete responder: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete responder")


@router.post("/api/responders/bulk-delete")
async def bulk_delete_responders(request: BulkDeleteRequest, _: dict = Depends(require_admin)) -> Dict[str, Any]:
    """Bulk delete multiple responder messages."""
    try:
        deleted_count = await run_in_threadpool(bulk_delete_messages, request.ids)
        return {"status": "deleted", "count": deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to bulk delete: {e}")
        raise HTTPException(status_code=500, detail="Failed to bulk delete")


@router.post("/api/clear-all")
async def clear_all_responders(_: dict = Depends(require_admin)) -> Dict[str, Any]:
    """Clear all active responders (soft delete)."""
    try:
        deleted_count = await run_in_threadpool(clear_all_messages)
        return {"status": "cleared", "count": deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to clear all: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear all")


@router.get("/api/deleted-responders")
async def get_deleted_responders(_: dict = Depends(require_admin)) -> List[Dict[str, Any]]:
    """Get all soft-deleted responder messages."""
    try:
        return await run_in_threadpool(get_deleted_messages)
    except Exception as e:
        logger.error(f"Failed to get deleted responders: {e}")
        raise HTTPException(status_code=500, detail="Failed to get deleted responders")


@router.post("/api/deleted-responders/undelete")
async def undelete_responder(request: UndeleteRequest, _: dict = Depends(require_admin)) -> Dict[str, Any]:
    """Restore a deleted responder message."""
    try:
        success = await run_in_threadpool(undelete_message, request.message_id)
        if not success:
            raise HTTPException(status_code=404, detail="Deleted message not found")
        
        # Get the restored message to return
        messages = await run_in_threadpool(get_messages)
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
async def permanently_delete_responder(msg_id: str, _: dict = Depends(require_admin)) -> Dict[str, str]:
    """Permanently delete a responder message."""
    try:
        success = await run_in_threadpool(permanently_delete_message, msg_id)
        if not success:
            raise HTTPException(status_code=404, detail="Deleted message not found")
        
        return {"status": "permanently_deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to permanently delete: {e}")
        raise HTTPException(status_code=500, detail="Failed to permanently delete")


@router.post("/api/deleted-responders/clear-all")
async def clear_all_deleted(_: dict = Depends(require_admin)) -> Dict[str, Any]:
    """Permanently delete all soft-deleted messages."""
    try:
        deleted_count = await run_in_threadpool(clear_all_deleted_messages)
        return {"status": "cleared", "count": deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to clear deleted: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear deleted")


@router.get("/api/storage-info")
async def get_storage_status(_: dict = Depends(require_auth)) -> Dict[str, Any]:
    """Get current storage backend status and configuration."""
    import socket
    import os
    try:
        storage_info = await run_in_threadpool(get_storage_info)
        # Add instance information for debugging
        storage_info["instance"] = {
            "hostname": socket.gethostname(),
            "replica": os.getenv("CONTAINER_APP_REPLICA_NAME", "unknown"),
            "revision": os.getenv("CONTAINER_APP_REVISION", "unknown"),
        }
        return storage_info
        
    except Exception as e:
        logger.error(f"Failed to get storage info: {e}")
        raise HTTPException(status_code=500, detail="Failed to get storage info")


@router.get("/api/wake")
async def wake_container() -> Dict[str, str]:
    """
    Wake endpoint to keep container warm when messages are enqueued.
    This endpoint requires no authentication and is called by Azure Function.
    """
    logger.info("Container wake request received")
    return {"status": "awake", "message": "Container is running"}


@router.post("/api/wake")
async def wake_container_post() -> Dict[str, str]:
    """
    POST version of wake endpoint for flexibility.
    This endpoint requires no authentication and is called by Azure Function.
    """
    logger.info("Container wake request received (POST)")
    return {"status": "awake", "message": "Container is running"}


async def _request_log_result() -> dict:
    import os

    if not os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
        raise HTTPException(status_code=503, detail="Request logging not configured")
    try:
        return await run_in_threadpool(read_recent_request_logs)
    except Exception:
        logger.error("Failed to fetch request logs")
        raise HTTPException(status_code=500, detail="Failed to fetch request logs") from None


@router.get("/api/request-logs")
async def get_request_logs(_: dict = Depends(require_admin)) -> List[Dict[str, Any]]:
    """Return the latest 100 request logs from the last 24 hours."""
    return (await _request_log_result())["logs"]


@router.get("/api/request-logs-debug")
async def get_request_logs_debug(_: dict = Depends(require_admin)) -> Dict[str, Any]:
    """Return recent request logs with query metadata."""
    return await _request_log_result()


@router.post("/api/retention/cleanup")
async def trigger_retention_cleanup(_: dict = Depends(require_admin)):
    """
    Manually trigger retention cleanup to purge old messages.
    This endpoint requires admin authentication.
    """
    from ..retention_scheduler import run_retention_cleanup_now
    from ..config import RETENTION_DAYS
    
    try:
        result = await run_retention_cleanup_now()
        return {
            "status": "success",
            "message": f"Retention cleanup completed (RETENTION_DAYS={RETENTION_DAYS})",
            "purged": result
        }
    except Exception:
        logger.error("Manual retention cleanup failed")
        raise HTTPException(status_code=500, detail="Retention cleanup failed") from None
