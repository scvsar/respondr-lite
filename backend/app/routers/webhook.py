"""Webhook and message parsing endpoints."""

from ..responder_identity import attach_responder_keys, message_epoch
from ..message_policy import is_system_notice, responder_messages

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from pydantic import BaseModel

from ..config import webhook_api_key, disable_api_key_check, APP_TZ, GROUP_ID_TO_TEAM
from ..llm import extract_details_from_text, build_prompts
from ..utils import parse_datetime_like
from ..storage import add_message, get_messages, get_deleted_messages
from ..auth.dependencies import require_admin, require_auth

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


def _build_storage_message_id(
    group_id: Optional[str],
    source_message_id: Optional[str],
) -> str:
    """Build an Azure Table-safe stable ID for a source message."""
    if not source_message_id:
        return str(uuid.uuid4())

    identity = f"{group_id or 'unknown'}:{source_message_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"groupme-{digest}"


def verify_api_key(api_key: Optional[str] = None):
    """Verify API key for webhook endpoints."""
    if disable_api_key_check:
        return True
    
    if not webhook_api_key:
        raise HTTPException(status_code=500, detail="API key not configured")
    
    if not api_key or api_key != webhook_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return True


def verify_webhook_request(request: Request):
    """Authenticate the HTTP entry point while keeping queue processing internal."""
    token = request.headers.get("X-Webhook-Token") or request.query_params.get("k")
    return verify_api_key(token)


@router.post("/webhook", dependencies=[Depends(verify_webhook_request)])
async def webhook_handler(message: WebhookMessage, request: Request, debug: bool = Query(default=False)):
    """Handle incoming webhook messages from GroupMe."""
    try:
        if debug:
            if request is None:
                raise HTTPException(status_code=401, detail="Sign-in required")
            header = request.headers.get("Authorization", "")
            token = header.split(" ", 1)[1] if header.lower().startswith("bearer ") else None
            require_admin(require_auth(request=request, token=token))
        # Parse timestamp
        message_dt = parse_datetime_like(message.created_at) or datetime.now(APP_TZ)
        if is_system_notice(message.model_dump()):
            notice = message.model_dump(include={
                "id", "name", "text", "created_at", "group_id", "sender_id",
                "sender_type", "source_guid", "user_id", "system", "attachments",
            })
            notice.update({
                "id": _build_storage_message_id(message.group_id, message.id),
                "groupme_id": message.id,
                "message_kind": "system",
                "timestamp": message_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp_utc": message_dt.astimezone(timezone.utc).isoformat(),
                "vehicle": "Unknown",
                "eta": "Unknown",
                "arrival_status": "Informational",
                "raw_status": "Informational",
                "status_source": "System",
            })
            if not await run_in_threadpool(add_message, notice):
                raise RuntimeError("Failed to save system notice")
            return {"status": "system_notice"}
        # Determine team from group_id early so we can scope history lookup
        group_id = message.group_id or "unknown"
        team = GROUP_ID_TO_TEAM.get(group_id, "Unknown")
        name_l = (message.name or "").strip().lower()
        storage_message_id = _build_storage_message_id(group_id, message.id)
        deleted_history = await run_in_threadpool(get_deleted_messages)
        history = responder_messages(await run_in_threadpool(get_messages) or [])

        # Look up previous ETA for this responder (same group) to allow persistence on updates
        prev_eta_iso: Optional[str] = None
        try:
            existing_message = next(
                (
                    item
                    for item in history
                    if item.get("id") == storage_message_id
                ),
                None,
            )
            if existing_message is None:
                existing_message = next((item for item in deleted_history
                                         if item.get('id') == storage_message_id), None)
            if existing_message is not None:
                logger.info(
                    "Skipped duplicate GroupMe message %s",
                    storage_message_id[:20],
                )
                if debug:
                    return {
                        "status": "duplicate",
                        "stored_message": existing_message,
                    }
                return {"status": "duplicate"}

            scoped = attach_responder_keys(history + [message.model_dump()])
            person_key = scoped[-1]['responder_key']
            recent_history = sorted((item for item in scoped[:-1]
                if item['responder_key'] == person_key
                and message.created_at - 12 * 3600 <= message_epoch(item) < message.created_at),
                key=message_epoch, reverse=True)
            if recent_history:
                latest = recent_history[0]
                if (latest.get('raw_status') or latest.get('arrival_status')) == 'Responding':
                    prev_eta_iso = latest.get('eta_timestamp_utc') or None
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
            scoped = attach_responder_keys(history + [message.model_dump()])
            person_key = scoped[-1]['responder_key']
            sorted_hist = sorted((item for item in scoped[:-1]
                if item['responder_key'] == person_key
                and cutoff_timestamp <= message_epoch(item) < message.created_at), key=message_epoch)
            for m in sorted_hist:
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

        # Debug callers have already passed authenticated admin authorization.
        sys_override = message.debug_sys_prompt if debug else None
        user_override = message.debug_user_prompt if debug else None
        verbosity_override = message.debug_verbosity if debug else None
        reasoning_override = message.debug_reasoning if debug else None
        max_tokens_override = message.debug_max_tokens if debug else None

        # Get recent responders for ETA validation context
        other_responders = []
        try:
            # Get all recent messages from this group for context
            recent_messages = history
            cutoff_time = message.created_at - (6 * 3600)  # 6 hours ago
            
            for m in recent_messages:
                # Only include messages from same group, within time window, with valid ETAs
                if (m.get("group_id") or "unknown") != group_id:
                    continue
                if m.get("created_at", 0) < cutoff_time:
                    continue
                    
                # Skip current user's own messages to avoid self-comparison
                if str(m.get("name", "")).strip().lower() == name_l:
                    continue
                    
                # Only include responding users with reasonable ETAs
                status = m.get("arrival_status") or m.get("raw_status")
                mins = m.get("minutes_until_arrival")
                eta_str = m.get("eta", "Unknown")
                
                if (status in ("Responding", "Available") and 
                    isinstance(mins, int) and 
                    -30 <= mins <= 600 and  # Within reasonable range
                    eta_str != "Unknown"):
                    
                    other_responders.append({
                        "name": m.get("name", "Unknown"),
                        "minutes_until_arrival": mins,
                        "eta": eta_str,
                        "vehicle": m.get("vehicle", "Unknown"),
                        "status": status
                    })
            
            # Keep only the most recent entry per responder
            seen_names = set()
            filtered_responders = []
            for r in sorted(other_responders, key=lambda x: x.get("minutes_until_arrival", 999), reverse=True):
                name_key = r["name"].lower().strip()
                if name_key not in seen_names:
                    seen_names.add(name_key)
                    filtered_responders.append(r)
            
            other_responders = filtered_responders[:10]  # Limit to 10 most relevant
            
        except Exception as e:
            logger.warning(f"Failed to get responder context for ETA validation: {e}")
            other_responders = []

        parsed = await run_in_threadpool(
            extract_details_from_text,
            enriched_text,
            base_time=message_dt,
            prev_eta_iso=prev_eta_iso,
            debug=debug,
            sys_prompt_override=sys_override,
            user_prompt_override=user_override,
            verbosity_override=verbosity_override,
            reasoning_effort_override=reasoning_override,
            max_tokens_override=max_tokens_override,
            other_responders=other_responders,
            original_text=message.text,
        )
        
        # Create message object
        minutes = parsed.get("minutes_until_arrival")
        arrival_status = parsed.get("arrival_status", parsed.get("raw_status", "Unknown"))
        if isinstance(minutes, int) and minutes <= 0 and arrival_status == "Responding":
            arrival_status = "Arrived"
        new_message = {
            "id": storage_message_id,
            "groupme_id": message.id,  # Store GroupMe message ID for debugging
            "sender_type": message.sender_type,
            "sender_id": message.sender_id,
            "user_id": message.user_id,
            "system": message.system,
            "message_kind": "responder",
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
            "extraction_failed": parsed.get("extraction_failed", False),
            "parse_source": parsed.get("parse_source", "LLM"),
            "team": team,
            "group_id": group_id,
            "created_at": message.created_at,
        }

        # Store message in storage layer
        if not await run_in_threadpool(add_message, new_message):
            raise RuntimeError("Failed to save responder message")
        logger.info("Processed GroupMe message %s", storage_message_id[:20])

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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail="Processing failed")


@router.get("/api/debug/default-prompts")
async def get_default_prompts(text: str, created_at: Optional[int] = None, prev_eta_iso: Optional[str] = None, _: dict = Depends(require_admin)):
    """Return the default system and user prompts the server would use for a given input.
    Helpful for the UI to prefill editable prompts.
    """
    
    base = parse_datetime_like(created_at) if created_at else datetime.now(APP_TZ)
    if base is None:
        base = datetime.now(APP_TZ)
    sys_p, user_p = build_prompts(text or "", base, prev_eta_iso)
    return {"sys_prompt": sys_p, "user_prompt": user_p}


@router.get("/api/config/groups")
async def get_config_groups(_: dict = Depends(require_admin)):
    """Return configured Group IDs and their team names. Admin-only."""

    try:
        items = [{"group_id": gid, "team": GROUP_ID_TO_TEAM.get(gid, "Unknown")} for gid in sorted(GROUP_ID_TO_TEAM.keys())]
        return {"groups": items}
    except Exception as e:
        logger.error(f"Failed to list groups: {e}")
        raise HTTPException(status_code=500, detail="Unable to list groups")


@router.post("/api/debug/webhook-raw")
async def webhook_raw(request: Request, payload: Dict[str, Any], _: dict = Depends(require_admin)):
    """Accept a raw GroupMe-style JSON and route it through webhook processing. Admin-only."""
    # Admin-only guard handled by dependency

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
async def parse_debug(request: ParseDebugRequest, _: dict = Depends(require_admin)):
    """Debug endpoint for testing message parsing. Admin-only."""
    try:
        base_time = None
        if request.base_time:
            base_time = parse_datetime_like(request.base_time)
        
        if not base_time:
            base_time = datetime.now(APP_TZ)
        
        result = await run_in_threadpool(
            extract_details_from_text,
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
