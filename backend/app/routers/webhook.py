"""Webhook and message parsing endpoints."""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from pydantic import BaseModel
import uuid

from ..config import webhook_api_key, disable_api_key_check, APP_TZ, GROUP_ID_TO_TEAM
from ..llm import extract_details_from_text, build_prompts
from ..utils import parse_datetime_like
from ..storage import add_message, get_messages
from .responders import require_admin_access

logger = logging.getLogger(__name__)
router = APIRouter()


class WebhookMessage(BaseModel):
    name: str
    text: str
    created_at: int
    group_id: Optional[str] = None
    # GroupMe fields (optional to maintain backward compatibility)
    id: Optional[str] = None  # GroupMe message ID
    sender_id: Optional[str] = None
    sender_type: Optional[str] = None
    source_guid: Optional[str] = None
    user_id: Optional[str] = None
    avatar_url: Optional[str] = None
    attachments: Optional[list] = None
    system: Optional[bool] = False
    # Admin-only debug extras (optional)
    debug_sys_prompt: Optional[str] = None
    debug_user_prompt: Optional[str] = None
    debug_verbosity: Optional[str] = None  # "low" | "medium" | "high"
    debug_reasoning: Optional[str] = None  # "low" | "medium" | "high"
    debug_max_tokens: Optional[int] = None  # override max_completion_tokens


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
async def webhook_handler(message: WebhookMessage, request: Request, debug: bool = Query(default=False)):
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
            # Look for the most recent ETA that was actually calculated (not inherited)
            for m in sorted(history, key=lambda x: x.get("created_at", 0), reverse=True):
                if (m.get("group_id") or "unknown") != group_id:
                    continue
                if str(m.get("name", "")).strip().lower() != name_l:
                    continue
                # Skip if this message is too recent (avoid using current message as previous)
                if m.get("created_at", 0) >= message.created_at:
                    continue
                # must have a valid prior ETA and have been responding
                eta_utc = m.get("eta_timestamp_utc")
                prior_status = m.get("raw_status") or m.get("arrival_status")
                parse_source = m.get("parse_source", "")
                
                # Prefer ETAs that were originally parsed from text (not inherited from previous)
                # to avoid perpetuating incorrect ETAs
                if eta_utc and eta_utc != "Unknown" and prior_status == "Responding":
                    prev_eta_iso = str(eta_utc)
                    # If this ETA was originally parsed from LLM or deterministic parsing
                    # (not inherited), use it and break
                    if parse_source in ("LLM", "Deterministic") and "inherit" not in parse_source.lower():
                        break
                    # Otherwise keep looking for a better source, but save this as fallback
        except Exception:
            # Non-fatal: proceed without prev ETA
            prev_eta_iso = None
        
        # Build full message history for this user to help the LLM maintain continuity
        # Include messages from the last 12 hours to avoid mixing different missions
        message_history_hours = 12  # Configurable time window
        cutoff_timestamp = message.created_at - (message_history_hours * 3600)
        
        user_history = []
        latest_eta: Optional[str] = None
        latest_vehicle: Optional[str] = None
        try:
            history = get_messages() or []
            # Sort by created_at ascending to build chronological history
            sorted_hist = sorted(history, key=lambda x: x.get("created_at", 0))
            
            for m in sorted_hist:
                # Only include messages from same group and user within time window
                if (m.get("group_id") or "unknown") != group_id:
                    continue
                if str(m.get("name", "")).strip().lower() != name_l:
                    continue
                if m.get("created_at", 0) < cutoff_timestamp:
                    continue
                    
                # Build history entry
                hist_entry = {
                    "text": m.get("text", ""),
                    "status": m.get("raw_status") or m.get("arrival_status", "Unknown"),
                    "vehicle": m.get("vehicle", "Unknown"),
                    "eta": m.get("eta", "Unknown"),
                    "timestamp": m.get("timestamp", "")
                }
                user_history.append(hist_entry)
                
                # Track latest values for fallback
                if m.get("vehicle") and m.get("vehicle") != "Unknown" and (m.get("arrival_status") or m.get("raw_status")) != "Cancelled":
                    latest_vehicle = str(m.get("vehicle"))
                if m.get("eta") and m.get("eta") != "Unknown" and (m.get("arrival_status") or m.get("raw_status")) != "Cancelled":
                    latest_eta = str(m.get("eta"))
                    
        except Exception as e:
            logger.warning(f"Failed to build user history: {e}")
            user_history = []
            latest_eta = None
            latest_vehicle = None

        # Format history for LLM
        enriched_text = message.text
        if user_history:
            # Include recent message history to give LLM full context
            history_text = "Previous messages from this user:\n"
            for h in user_history[-5:]:  # Last 5 messages max to avoid token overflow
                history_text += f"- [{h['timestamp']}] \"{h['text']}\" -> Status: {h['status']}, Vehicle: {h['vehicle']}, ETA: {h['eta']}\n"
            enriched_text = f"{history_text}\nCurrent message: {message.text}"
        elif latest_eta or latest_vehicle:
            # Fallback to compact snapshot if no full history
            parts = []
            if latest_eta:
                parts.append(f"last ETA was {latest_eta}")
            if latest_vehicle:
                parts.append(f"last vehicle was {latest_vehicle}")
            snapshot = "; ".join(parts)
            enriched_text = f"History: {snapshot}. Current: {message.text}"

        # Extract details using LLM with history snapshot and previous ETA
        # Include prompt overrides only for admin users in debug mode
        sys_override = None
        user_override = None
        if debug and (
            message.debug_sys_prompt is not None
            or message.debug_user_prompt is not None
            or message.debug_verbosity is not None
            or message.debug_reasoning is not None
            or message.debug_max_tokens is not None
        ):
            try:
                from .user import is_admin
                user_email = (
                    request.headers.get("X-Auth-Request-Email")
                    or request.headers.get("X-Auth-Request-User")
                    or request.headers.get("x-forwarded-email")
                    or request.headers.get("X-User")
                ) if request else None
                if is_admin(user_email):
                    sys_override = message.debug_sys_prompt
                    user_override = message.debug_user_prompt
                    verbosity_override = message.debug_verbosity
                    reasoning_override = message.debug_reasoning
                    max_tokens_override = message.debug_max_tokens
                else:
                    # ignore overrides for non-admin
                    sys_override = None
                    user_override = None
                    verbosity_override = None
                    reasoning_override = None
                    max_tokens_override = None
            except Exception:
                sys_override = None
                user_override = None
                verbosity_override = None
                reasoning_override = None
                max_tokens_override = None
        else:
            verbosity_override = None
            reasoning_override = None
            max_tokens_override = None

        parsed = extract_details_from_text(
            enriched_text,
            base_time=message_dt,
            prev_eta_iso=prev_eta_iso,
            debug=debug,
            sys_prompt_override=sys_override,
            user_prompt_override=user_override,
            verbosity_override=verbosity_override,
            reasoning_effort_override=reasoning_override,
            max_tokens_override=max_tokens_override,
        )
        
        # Create message object
        minutes = parsed.get("minutes_until_arrival")
        arrival_status = parsed.get("arrival_status", parsed.get("raw_status", "Unknown"))
        if isinstance(minutes, int) and minutes <= 0 and arrival_status == "Responding":
            arrival_status = "Arrived"
        new_message = {
            "id": str(uuid.uuid4()),
            "groupme_id": message.id,  # Store GroupMe message ID for debugging
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
            # Admin-only: require authenticated admin for debug payloads
            try:
                # Use the same admin check as other endpoints
                require_admin_access(request)
            except HTTPException:
                raise
            except Exception:
                # Fail closed if we can't determine auth
                raise HTTPException(status_code=403, detail="Debug access requires admin")
            return {
                "status": "ok",
                "inputs": {
                    "enriched_text": enriched_text,
                    "original_text": message.text,
                    "prev_eta_iso": prev_eta_iso,
                    "base_time": message_dt.isoformat(),
                    "group_id": group_id,
                    "team": team,
                    "sys_prompt_override": message.debug_sys_prompt,
                    "user_prompt_override": message.debug_user_prompt,
                    "verbosity_override": message.debug_verbosity,
                    "reasoning_override": message.debug_reasoning,
                    "max_tokens_override": message.debug_max_tokens,
                },
                "parsed": parsed,
                "stored_message": new_message,
            }

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail="Processing failed")


@router.get("/api/debug/default-prompts")
async def get_default_prompts(text: str, created_at: Optional[int] = None, prev_eta_iso: Optional[str] = None, _: bool = Depends(require_admin_access)):
    """Return the default system and user prompts the server would use for a given input.
    Helpful for the UI to prefill editable prompts.
    """
    
    base = parse_datetime_like(created_at) if created_at else datetime.now(APP_TZ)
    if base is None:
        base = datetime.now(APP_TZ)
    sys_p, user_p = build_prompts(text or "", base, prev_eta_iso)
    return {"sys_prompt": sys_p, "user_prompt": user_p}


@router.get("/api/config/groups")
async def get_config_groups(_: bool = Depends(require_admin_access)):
    """Return configured Group IDs and their team names. Admin-only."""

    try:
        items = [{"group_id": gid, "team": GROUP_ID_TO_TEAM.get(gid, "Unknown")} for gid in sorted(GROUP_ID_TO_TEAM.keys())]
        return {"groups": items}
    except Exception as e:
        logger.error(f"Failed to list groups: {e}")
        raise HTTPException(status_code=500, detail="Unable to list groups")


@router.post("/api/debug/webhook-raw")
async def webhook_raw(request: Request, payload: Dict[str, Any]):
    """Accept a raw GroupMe-style JSON and route it through webhook processing. Admin-only."""
    # Admin-only guard
    try:
        from .user import is_admin
        user_email = (
            request.headers.get("X-Auth-Request-Email")
            or request.headers.get("X-Auth-Request-User")
            or request.headers.get("x-forwarded-email")
            or request.headers.get("X-User")
        ) if request else None
        if not is_admin(user_email):
            raise HTTPException(status_code=403, detail="Admin only")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=403, detail="Admin only")

    try:
        # Extract fields from typical GroupMe message structure
        name = str(payload.get("name") or payload.get("sender", "")).strip() or "Unknown"
        text = str(payload.get("text") or "").strip()
        created_at_raw = payload.get("created_at")
        if created_at_raw is None:
            created_at = int(datetime.now(APP_TZ).timestamp())
        else:
            try:
                created_at = int(created_at_raw)  # epoch seconds
            except Exception:
                # allow ISO strings
                dt = parse_datetime_like(created_at_raw) or datetime.now(APP_TZ)
                created_at = int(dt.timestamp())
        group_id = str(payload.get("group_id") or "unknown")

        # Optional debug overrides if present at top-level
        debug_sys_prompt = payload.get("debug_sys_prompt")
        debug_user_prompt = payload.get("debug_user_prompt")
        debug_verbosity = payload.get("debug_verbosity")
        debug_reasoning = payload.get("debug_reasoning")
        debug_max_tokens = payload.get("debug_max_tokens")

        msg = WebhookMessage(
            name=name,
            text=text,
            created_at=created_at,
            group_id=group_id,
            debug_sys_prompt=debug_sys_prompt,
            debug_user_prompt=debug_user_prompt,
            debug_verbosity=debug_verbosity,
            debug_reasoning=debug_reasoning,
            debug_max_tokens=debug_max_tokens,
        )
        # Reuse main handler with debug=True to return rich info
        return await webhook_handler(msg, request, debug=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"webhook-raw failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid raw payload")


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
