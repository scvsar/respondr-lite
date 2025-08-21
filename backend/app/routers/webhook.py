"""Webhook and message parsing endpoints."""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from pydantic import BaseModel
import uuid

from ..config import webhook_api_key, disable_api_key_check, APP_TZ, GROUP_ID_TO_TEAM
from ..llm import extract_details_from_text
from ..utils import parse_datetime_like
from ..storage import add_message, get_messages

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
async def webhook_handler(message: WebhookMessage, debug: bool = Query(default=False)):
    """Handle incoming webhook messages from GroupMe."""
    try:
        # Parse timestamp
        message_dt = parse_datetime_like(message.created_at) or datetime.now(APP_TZ)
        # Determine team from group_id early so we can scope history lookup
        group_id = message.group_id or "unknown"
        team = GROUP_ID_TO_TEAM.get(group_id, "Unknown")
        name_l = (message.name or "").strip().lower()

        # Look up previous ETA for this responder (same group) to allow persistence on updates
        prev_eta_iso: Optional[str] = None
        try:
            history = get_messages() or []
            # Sort latest first; prefer same group_id and same name
            for m in sorted(history, key=lambda x: x.get("created_at", 0), reverse=True):
                if (m.get("group_id") or "unknown") != group_id:
                    continue
                if str(m.get("name", "")).strip().lower() != name_l:
                    continue
                # must have a valid prior ETA and have been responding
                eta_utc = m.get("eta_timestamp_utc")
                prior_status = m.get("raw_status") or m.get("arrival_status")
                if eta_utc and eta_utc != "Unknown" and prior_status == "Responding":
                    prev_eta_iso = str(eta_utc)
                    break
        except Exception:
            # Non-fatal: proceed without prev ETA
            prev_eta_iso = None
        
        # Build a compact history snapshot to help the LLM maintain continuity (monolith parity)
        latest_eta: Optional[str] = None
        latest_vehicle: Optional[str] = None
        try:
            history = get_messages() or []
            # Sort by created_at ascending to easily scan from end
            sorted_hist = sorted(history, key=lambda x: x.get("created_at", 0))
            # Find most recent non-cancelled ETA and vehicle for this user in this group
            for m in reversed(sorted_hist):
                if (m.get("group_id") or "unknown") != group_id:
                    continue
                if str(m.get("name", "")).strip().lower() != name_l:
                    continue
                # vehicle
                if latest_vehicle is None:
                    if (m.get("vehicle") and m.get("vehicle") != "Unknown" and (m.get("arrival_status") or m.get("raw_status")) != "Cancelled"):
                        latest_vehicle = str(m.get("vehicle"))
                # eta
                if latest_eta is None:
                    if (m.get("eta") and m.get("eta") != "Unknown" and (m.get("arrival_status") or m.get("raw_status")) != "Cancelled"):
                        latest_eta = str(m.get("eta"))
                if latest_vehicle is not None and latest_eta is not None:
                    break
        except Exception:
            latest_eta = None
            latest_vehicle = None

        enriched_text = message.text
        if latest_eta or latest_vehicle:
            # Keep it short; the LLM prompt explicitly allows a history snapshot in the message body
            parts = []
            if latest_eta:
                parts.append(f"last ETA was {latest_eta}")
            if latest_vehicle:
                parts.append(f"last vehicle was {latest_vehicle}")
            snapshot = "; ".join(parts)
            enriched_text = f"History: {snapshot}. Current: {message.text}"

        # Extract details using LLM with history snapshot and previous ETA
        parsed = extract_details_from_text(
            enriched_text,
            base_time=message_dt,
            prev_eta_iso=prev_eta_iso,
            debug=debug,
        )
        
        # Create message object
        minutes = parsed.get("minutes_until_arrival")
        arrival_status = parsed.get("arrival_status", parsed.get("raw_status", "Unknown"))
        if isinstance(minutes, int) and minutes <= 0 and arrival_status == "Responding":
            arrival_status = "Arrived"
        new_message = {
            "id": str(uuid.uuid4()),
            "name": message.name,
            "text": message.text,
            "timestamp": message_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_utc": message_dt.astimezone(timezone.utc).isoformat(),
            "vehicle": parsed["vehicle"],
            "eta": parsed["eta"],
            "eta_timestamp": parsed["eta_timestamp"],
            "eta_timestamp_utc": parsed["eta_timestamp_utc"],
            "minutes_until_arrival": parsed["minutes_until_arrival"],
            "arrival_status": arrival_status,
            "raw_status": parsed["raw_status"],
            "status_source": parsed["status_source"],
            "status_confidence": parsed["status_confidence"],
            "team": team,
            "group_id": group_id,
            "created_at": message.created_at,
        }
        
        # Store message in storage layer
        add_message(new_message)
        logger.info(
            f"Processed webhook message from {message.name}: {parsed['vehicle']} ETA {parsed['eta']}"
            + (f" (prev_eta carried)" if prev_eta_iso else "")
        )

        if debug:
            return {
                "status": "ok",
                "inputs": {
                    "enriched_text": enriched_text,
                    "original_text": message.text,
                    "prev_eta_iso": prev_eta_iso,
                    "base_time": message_dt.isoformat(),
                    "group_id": group_id,
                    "team": team,
                },
                "parsed": parsed,
                "stored_message": new_message,
            }

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
