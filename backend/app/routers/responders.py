"""Responders API endpoints for managing SAR response messages."""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import APP_TZ
from ..utils import parse_datetime_like, compute_eta_fields
from ..storage import (
    get_messages, add_message, update_message, delete_message, 
    get_deleted_messages, undelete_message, permanently_delete_message,
    clear_all_messages, clear_all_deleted_messages, bulk_delete_messages
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ResponderUpdate(BaseModel):
    name: Optional[str] = None
    vehicle: Optional[str] = None
    eta: Optional[str] = None
    eta_timestamp: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    message_ids: List[str]


class UndeleteRequest(BaseModel):
    message_id: str


# Remove in-memory storage - using storage layer now


@router.get("/api/responders")
async def get_responders():
    """Get all active responder messages."""
    try:
        messages = get_messages()
        return messages
    except Exception as e:
        logger.error(f"Failed to get responders: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve responders")


@router.get("/api/current-status")
async def get_current_status():
    """Get current status summary of all responders."""
    try:
        messages = get_messages()
        
        total = len(messages)
        responding = len([m for m in messages if m.get("arrival_status") == "Responding"])
        arrived = len([m for m in messages if m.get("arrival_status") == "Arrived"])
        overdue = len([m for m in messages if m.get("arrival_status") == "Overdue"])
        
        return {
            "total_responders": total,
            "responding": responding,
            "arrived": arrived,
            "overdue": overdue,
            "last_updated": datetime.now(APP_TZ).isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get current status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get status")


@router.post("/api/responders")
async def create_responder(data: Dict[str, Any]):
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
            "group_id": data.get("group_id", "manual"),
            "created_at": int(timestamp.timestamp()),
        }
        
        # Store in storage layer
        add_message(message)
        
        return {"status": "created", "message": message}
        
    except Exception as e:
        logger.error(f"Failed to create responder: {e}")
        raise HTTPException(status_code=500, detail="Failed to create responder")


@router.put("/api/responders/{msg_id}")
async def update_responder(msg_id: str, update: ResponderUpdate):
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
async def delete_responder(msg_id: str):
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
async def bulk_delete_responders(request: BulkDeleteRequest):
    """Bulk delete multiple responder messages."""
    try:
        deleted_count = bulk_delete_messages(request.message_ids)
        return {"status": "deleted", "count": deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to bulk delete: {e}")
        raise HTTPException(status_code=500, detail="Failed to bulk delete")


@router.post("/api/clear-all")
async def clear_all_responders():
    """Clear all active responders (soft delete)."""
    try:
        deleted_count = clear_all_messages()
        return {"status": "cleared", "count": deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to clear all: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear all")


@router.get("/api/deleted-responders")
async def get_deleted_responders():
    """Get all soft-deleted responder messages."""
    try:
        return get_deleted_messages()
    except Exception as e:
        logger.error(f"Failed to get deleted responders: {e}")
        raise HTTPException(status_code=500, detail="Failed to get deleted responders")


@router.post("/api/deleted-responders/undelete")
async def undelete_responder(request: UndeleteRequest):
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
async def permanently_delete_responder(msg_id: str):
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
async def clear_all_deleted():
    """Permanently delete all soft-deleted messages."""
    try:
        deleted_count = clear_all_deleted_messages()
        return {"status": "cleared", "count": deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to clear deleted: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear deleted")