"""Webhook and message parsing endpoints."""

import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from pydantic import BaseModel
import uuid

from ..config import webhook_api_key, disable_api_key_check, APP_TZ
from ..llm import extract_details_from_text
from ..utils import parse_datetime_like
from ..storage import add_message

logger = logging.getLogger(__name__)
router = APIRouter()


class WebhookMessage(BaseModel):
    name: str
    text: str
    created_at: int
    group_id: Optional[str] = None


class ParseDebugRequest(BaseModel):
    text: str
    base_time: Optional[str] = None
    prev_eta_iso: Optional[str] = None


def verify_api_key(api_key: Optional[str] = None):
    """Verify API key for webhook endpoints."""
    if disable_api_key_check:
        return True
    
    if not webhook_api_key:
        raise HTTPException(status_code=500, detail="API key not configured")
    
    if not api_key or api_key != webhook_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return True


@router.post("/webhook")
async def webhook_handler(message: WebhookMessage):
    """Handle incoming webhook messages from GroupMe."""
    try:
        # Parse timestamp
        message_dt = parse_datetime_like(message.created_at) or datetime.now(APP_TZ)
        
        # Extract details using LLM
        parsed = extract_details_from_text(message.text, base_time=message_dt)
        
        # Create message object
        new_message = {
            "id": str(uuid.uuid4()),
            "name": message.name,
            "text": message.text,
            "timestamp": message_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "vehicle": parsed["vehicle"],
            "eta": parsed["eta"],
            "eta_timestamp": parsed["eta_timestamp"],
            "eta_timestamp_utc": parsed["eta_timestamp_utc"],
            "minutes_until_arrival": parsed["minutes_until_arrival"],
            "arrival_status": parsed.get("arrival_status", "Unknown"),
            "raw_status": parsed["raw_status"],
            "status_source": parsed["status_source"],
            "status_confidence": parsed["status_confidence"],
            "group_id": message.group_id or "unknown",
            "created_at": message.created_at,
        }
        
        # Store message in storage layer
        add_message(new_message)
        logger.info(f"Processed webhook message from {message.name}: {parsed['vehicle']} ETA {parsed['eta']}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail="Processing failed")


@router.post("/api/parse-debug")
async def parse_debug(request: ParseDebugRequest):
    """Debug endpoint for testing message parsing."""
    try:
        base_time = None
        if request.base_time:
            base_time = parse_datetime_like(request.base_time)
        
        if not base_time:
            base_time = datetime.now(APP_TZ)
        
        result = extract_details_from_text(
            request.text, 
            base_time=base_time,
            prev_eta_iso=request.prev_eta_iso
        )
        
        return {
            "input": {
                "text": request.text,
                "base_time": base_time.isoformat(),
                "prev_eta_iso": request.prev_eta_iso
            },
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Parse debug failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))