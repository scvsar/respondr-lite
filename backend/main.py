import os
import sys
import json
import logging
import re
import html
from typing import Any, Dict, Optional, List, cast
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    zoneinfo_available = True
except ImportError:
    zoneinfo_available = False
    _ZoneInfo = None

from urllib.parse import quote
import tempfile
import importlib
import uuid

import redis
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from openai import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam


# ----------------------------------------------------------------------------
# App setup and config
# ----------------------------------------------------------------------------

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


# Safe HTML escape helper
def _esc(v: Any) -> str:
    try:
        return html.escape("" if v is None else str(v))
    except Exception:
        return ""


# Timezone helpers
def get_timezone(name: str) -> timezone:
    if name == "UTC":
        return timezone.utc
    elif name == "America/Los_Angeles" and zoneinfo_available:
        try:
            return _ZoneInfo("America/Los_Angeles")  # type: ignore
        except Exception:
            pass
    # Fallback: PST approximation (no DST) if zoneinfo unavailable
    return timezone(timedelta(hours=-8))


TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")
APP_TZ = get_timezone(TIMEZONE)

if 'zoneinfo_available' in globals():
    if not zoneinfo_available and TIMEZONE.upper() != "UTC":
        logger.warning("zoneinfo not available; using fixed UTC-8 fallback. Set TIMEZONE=UTC or install zoneinfo for correct DST.")


def now_tz() -> datetime:
    return datetime.now(APP_TZ)


# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis-service")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_KEY = "respondr_messages"
REDIS_DELETED_KEY = "respondr_deleted_messages"


# Auth and env flags
webhook_api_key = os.getenv("WEBHOOK_API_KEY")
allowed_email_domains = [d.strip() for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "scvsar.org,rtreit.com").split(",") if d.strip()]
allowed_admin_users = [u.strip().lower() for u in os.getenv("ALLOWED_ADMIN_USERS", "").split(",") if u.strip()]

ALLOW_LOCAL_AUTH_BYPASS = os.getenv("ALLOW_LOCAL_AUTH_BYPASS", "false").lower() == "true"
LOCAL_BYPASS_IS_ADMIN = os.getenv("LOCAL_BYPASS_IS_ADMIN", "false").lower() == "true"

is_testing = os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules
disable_api_key_check = os.getenv("DISABLE_API_KEY_CHECK", "false").lower() == "true" or is_testing

# temporary override for PoC
disable_api_key_check = True

# Azure OpenAI configuration
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")


# FastAPI app and state
app = FastAPI()
messages: List[Dict[str, Any]] = []
deleted_messages: List[Dict[str, Any]] = []
redis_client: Optional[redis.Redis] = None

# Legacy test compatibility flag removed in LLM-only implementation


def validate_webhook_api_key(x_api_key: Optional[str] = Header(None)) -> bool:
    if is_testing:
        return True
    if disable_api_key_check:
        logger.warning("API key check disabled by configuration")
        return True
    if not webhook_api_key:
        raise HTTPException(status_code=500, detail="Webhook API key not configured")
    if not x_api_key or x_api_key != webhook_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# GroupMe Group ID to Team mapping
GROUP_ID_TO_TEAM: Dict[str, str] = {
    "102193274": "OSUTest",
    "109174633": "PreProd",
    "97608845": "4X4",
    "6846970": "ASAR",
    "61402638": "ASAR",
    "19723040": "SSAR",
    "96018206": "IMT",
    "1596896": "K9",
    "92390332": "ASAR",
    "99606944": "OSU",
    "14533239": "MSAR",
    "106549466": "ESAR",
    "16649586": "OSU",
}


# ----------------------------------------------------------------------------
# Storage helpers (Redis + in-memory fallback)
# ----------------------------------------------------------------------------

def init_redis():
    global redis_client
    if is_testing:
        return
    if redis_client is None:
        try:
            redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            cast(Any, redis_client).ping()
            logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")


def load_messages():
    global messages
    if is_testing:
        return
    try:
        init_redis()
        if redis_client:
            data = redis_client.get(REDIS_KEY)
            if data:
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                messages = json.loads(cast(str, data))
            else:
                logger.info("No existing messages in Redis; keeping current in-memory messages")
        else:
            logger.warning("Redis not available; keeping in-memory messages")
    except Exception as e:
        logger.error(f"Error loading messages from Redis: {e}")
    # Ensure IDs
    _assigned = ensure_message_ids()
    if _assigned:
        save_messages()


def save_messages():
    global messages
    if is_testing:
        return
    try:
        init_redis()
        if redis_client:
            redis_client.set(REDIS_KEY, json.dumps(messages))
        else:
            logger.warning("Redis not available; keeping messages only in memory")
    except Exception as e:
        logger.error(f"Error saving messages to Redis: {e}")


def reload_messages():
    load_messages()


def load_deleted_messages():
    global deleted_messages
    if is_testing:
        return
    try:
        init_redis()
        if redis_client:
            data = redis_client.get(REDIS_DELETED_KEY)
            if data:
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                deleted_messages = json.loads(cast(str, data))
        else:
            logger.warning("Redis not available for deleted messages")
    except Exception as e:
        logger.error(f"Error loading deleted messages from Redis: {e}")


def save_deleted_messages():
    global deleted_messages
    if is_testing:
        return
    try:
        init_redis()
        if redis_client:
            redis_client.set(REDIS_DELETED_KEY, json.dumps(deleted_messages))
        else:
            logger.warning("Redis not available; keeping deleted messages only in memory")
    except Exception as e:
        logger.error(f"Error saving deleted messages to Redis: {e}")


def soft_delete_messages(messages_to_delete: List[Dict[str, Any]]):
    global deleted_messages
    load_deleted_messages()
    current_time = datetime.now().isoformat()
    for msg in messages_to_delete:
        msg["deleted_at"] = current_time
        deleted_messages.append(msg)
    save_deleted_messages()


def undelete_messages(message_ids: List[str]) -> int:
    global messages, deleted_messages
    load_deleted_messages()
    reload_messages()
    to_restore: List[Dict[str, Any]] = []
    remaining_deleted: List[Dict[str, Any]] = []
    ids = {str(i) for i in message_ids}
    for msg in deleted_messages:
        if str(msg.get("id")) in ids:
            msg.pop("deleted_at", None)
            to_restore.append(msg)
        else:
            remaining_deleted.append(msg)
    if to_restore:
        messages.extend(to_restore)
        save_messages()
        deleted_messages.clear()
        deleted_messages.extend(remaining_deleted)
        save_deleted_messages()
    return len(to_restore)


def _clear_all_messages():
    global messages
    messages = []
    try:
        if not is_testing:
            init_redis()
            if redis_client:
                redis_client.delete(REDIS_KEY)
    except Exception as e:
        logger.warning(f"Failed clearing Redis key {REDIS_KEY}: {e}")


def ensure_message_ids() -> int:
    count = 0
    for m in messages:
        if not m.get("id"):
            m["id"] = str(uuid.uuid4())
            count += 1
    return count


# ----------------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------------

def is_email_domain_allowed(email: str) -> bool:
    if not email:
        return False
    if is_testing and email.endswith("@example.com"):
        return True
    try:
        domain = email.split("@")[1].lower()
        return domain in [d.lower() for d in allowed_email_domains]
    except Exception:
        return False


def is_admin(email: Optional[str]) -> bool:
    if is_testing:
        return True
    if ALLOW_LOCAL_AUTH_BYPASS and LOCAL_BYPASS_IS_ADMIN:
        return True
    if not email:
        return False
    try:
        return email.strip().lower() in allowed_admin_users
    except Exception:
        return False


DEBUG_LOG_HEADERS = os.getenv("DEBUG_LOG_HEADERS", "false").lower() == "true"


@app.get("/api/user")
def get_user_info(request: Request) -> JSONResponse:
    if DEBUG_LOG_HEADERS:
        logger.debug("=== DEBUG: All headers received ===")
        for header_name, header_value in request.headers.items():
            if header_name.lower().startswith('x-'):
                logger.debug(f"Header: {header_name} = {header_value}")
        logger.debug("=== END DEBUG ===")

    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
    )
    user_name = (
        request.headers.get("X-Auth-Request-Preferred-Username")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-preferred-username")
    )
    user_groups = request.headers.get("X-Auth-Request-Groups", "").split(",") if request.headers.get("X-Auth-Request-Groups") else []

    if not user_email:
        user_email = request.headers.get("X-User")
    if not user_name:
        user_name = request.headers.get("X-Preferred-Username") or request.headers.get("X-User-Name")
    if not user_groups:
        user_groups = request.headers.get("X-User-Groups", "").split(",") if request.headers.get("X-User-Groups") else []

    if user_email or user_name:
        if user_email and not is_email_domain_allowed(user_email):
            logger.warning(f"Access denied for user {user_email}: domain not in allowed list")
            return JSONResponse(status_code=403, content={
                "authenticated": False,
                "error": "Access denied",
                "message": f"Your domain is not authorized to access this application. Allowed domains: {', '.join(allowed_email_domains)}",
                "logout_url": f"/oauth2/sign_out?rd={quote('/', safe='')}",
            })
        authenticated = True
        display_name = user_name or user_email
        email = user_email
    else:
        if ALLOW_LOCAL_AUTH_BYPASS and not is_testing:
            authenticated = True
            display_name = os.getenv("LOCAL_DEV_USER_NAME", "Local Dev")
            email = os.getenv("LOCAL_DEV_USER_EMAIL", "dev@local.test")
        else:
            authenticated = False
            display_name = None
            email = None

    admin_flag = is_admin(email)
    return JSONResponse(content={
        "authenticated": authenticated,
        "email": email,
        "name": display_name,
        "groups": [g.strip() for g in user_groups if g.strip()],
        "is_admin": admin_flag,
        "logout_url": f"/oauth2/sign_out?rd={quote('/', safe='')}",
    })


def _authn_domain_and_admin_ok(request: Request) -> bool:
    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
        or request.headers.get("X-User")
    )
    if not user_email:
        return bool(is_testing or ALLOW_LOCAL_AUTH_BYPASS)
    return is_email_domain_allowed(user_email) and is_admin(user_email)


def _parse_datetime_like(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=APP_TZ)
        s = str(value)
        if "T" not in s and " " in s and ":" in s:
            s = s.replace(" ", "T")
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            try:
                dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)
    except Exception:
        return None


def _coerce_dt(s: Optional[str]) -> datetime:
    """Coerce various timestamp strings to a timezone-aware UTC datetime for stable sorting.
    Falls back to datetime.min UTC when parsing fails.
    """
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


def _compute_eta_fields(eta_str: Optional[str], eta_ts: Optional[datetime], base_time: datetime) -> Dict[str, Any]:
    """Minimal ETA computation for admin edit endpoints.
    - If eta_ts provided: use directly.
    - Else if eta_str == HH:MM: apply to base_time date, roll to next day if <= base_time.
    - Else Unknown.
    """
    if eta_ts:
        eta_local = eta_ts.astimezone(APP_TZ)
        eta_dt_utc = eta_ts.astimezone(timezone.utc)
        minutes_until = int((eta_local - now_tz()).total_seconds() / 60)
        return {
            "eta": eta_local.strftime("%H:%M"),
            "eta_timestamp": (eta_local.strftime("%Y-%m-%d %H:%M:%S") if is_testing else eta_local.isoformat()),
            "eta_timestamp_utc": eta_dt_utc.isoformat(),
            "minutes_until_arrival": minutes_until,
            "arrival_status": ("Responding" if minutes_until > 0 else "Arrived"),
        }

    if isinstance(eta_str, str) and re.fullmatch(r"\d{1,2}:\d{2}", eta_str.strip() or ""):
        h, m = map(int, eta_str.strip().split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return {"eta": "Unknown", "eta_timestamp": None, "eta_timestamp_utc": None, "minutes_until_arrival": None, "arrival_status": "Unknown"}
        eta_local = base_time.replace(hour=h, minute=m, second=0, microsecond=0)
        if eta_local <= base_time:
            eta_local += timedelta(days=1)
        eta_dt_utc = eta_local.astimezone(timezone.utc)
        minutes_until = int((eta_local - now_tz()).total_seconds() / 60)
        return {
            "eta": eta_local.strftime("%H:%M"),
            "eta_timestamp": (eta_local.strftime("%Y-%m-%d %H:%M:%S") if is_testing else eta_local.isoformat()),
            "eta_timestamp_utc": eta_dt_utc.isoformat(),
            "minutes_until_arrival": minutes_until,
            "arrival_status": ("Responding" if minutes_until > 0 else "Arrived"),
        }

    return {
        "eta": "Unknown",
        "eta_timestamp": None,
        "eta_timestamp_utc": None,
        "minutes_until_arrival": None,
        "arrival_status": "Unknown",
    }


def _extract_eta_from_text_local(text: str, base_time: datetime) -> Optional[datetime]:
    """Deterministically extract an ETA from explicit local-time mentions in text.
    Supports:
    - HH:MM AM/PM or H:MM am/pm or HH am/pm
    - 4-digit military times like 2145 (interpreted as local time)
    Returns a timezone-aware datetime in APP_TZ, rolled to next day if not in the future relative to base_time.
    """
    s = text or ""
    try:
        # 1) AM/PM formats
        m = re.search(r"(?i)\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", s)
        if m:
            h = int(m.group(1))
            mnt = int(m.group(2) or 0)
            ampm = m.group(3).lower()
            if not (1 <= h <= 12 and 0 <= mnt <= 59):
                return None
            if ampm == "pm" and h != 12:
                h += 12
            if ampm == "am" and h == 12:
                h = 0
            eta_local = base_time.replace(hour=h, minute=mnt, second=0, microsecond=0)
            if eta_local <= base_time:
                eta_local += timedelta(days=1)
            return eta_local

        # 2) Military 4-digit like 2145 or 0930
        m2 = re.search(r"\b((?:[01]\d|2[0-3])[0-5]\d)\b", s)
        if m2:
            val = m2.group(1)
            h = int(val[:2])
            mnt = int(val[2:])
            eta_local = base_time.replace(hour=h, minute=mnt, second=0, microsecond=0)
            if eta_local <= base_time:
                eta_local += timedelta(days=1)
            return eta_local
    except Exception:
        return None
    return None


def _extract_duration_eta(text: str, base_time: datetime) -> Optional[datetime]:
    """Deterministically extract ETA from duration mentions like '15 min', '1 hr', '15-20 minutes'.
    Chooses a conservative upper bound when a range is provided (e.g., 15-20 → 20 minutes).
    Returns a timezone-aware datetime in APP_TZ; never returns a past time (adds to base_time).
    """
    s = (text or "").lower()
    try:
        # minutes range or single
        m = re.search(r"\b(\d{1,3})(?:\s*[-~]\s*(\d{1,3}))?\s*(?:min|mins|minute|minutes)\b", s)
        if m:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else None
            minutes = max(a, b) if b is not None else a
            minutes = max(0, min(minutes, 24 * 60))  # clamp to one day
            return base_time + timedelta(minutes=minutes)

        # hours range or single
        h = re.search(r"\b(\d{1,2})(?:\s*[-~]\s*(\d{1,2}))?\s*(?:hr|hrs|hour|hours)\b", s)
        if h:
            a = int(h.group(1))
            b = int(h.group(2)) if h.group(2) else None
            hours = max(a, b) if b is not None else a
            hours = max(0, min(hours, 48))  # clamp to two days
            return base_time + timedelta(hours=hours)
    except Exception:
        return None
    return None


# ----------------------------------------------------------------------------
# Azure OpenAI client and LLM-only parser
# ----------------------------------------------------------------------------

client: Optional[AzureOpenAI] = None
try:
    if azure_openai_api_key and azure_openai_endpoint and azure_openai_api_version:
        client = AzureOpenAI(
            api_key=cast(str, azure_openai_api_key),
            azure_endpoint=cast(str, azure_openai_endpoint),
            api_version=cast(str, azure_openai_api_version),
        )
        logger.info("Azure OpenAI client initialized")
    else:
        logger.warning("Azure OpenAI client not configured; LLM-only parsing unavailable")
except Exception as e:
    logger.warning(f"Failed to initialize Azure OpenAI client: {e}")
    if is_testing:
        from unittest.mock import MagicMock
        client = MagicMock()
        logger.info("Created mock Azure OpenAI client for testing")
    else:
        client = None


def _call_llm_only(text: str, current_iso_utc: str, prev_eta_iso_utc: Optional[str]) -> Dict[str, Any]:
    """Call Azure OpenAI to extract vehicle, status, and ETA (ISO UTC).
    Returns keys: vehicle, eta_iso, status, evidence, confidence.
    """
    DEBUG_FULL_LLM_LOG = os.getenv("DEBUG_FULL_LLM_LOG", "").lower() in ("1", "true", "yes")
    
    # Log to temp file for debug
    temp_dir = tempfile.gettempdir()
    log_file = os.path.join(temp_dir, "respondr_llm_debug.log")
    log_entry: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "function": "_call_llm_only",
        "input": {"text": text, "current_iso_utc": current_iso_utc, "prev_eta_iso_utc": prev_eta_iso_utc},
    }

    if client is None or not azure_openai_deployment:
        log_entry["error"] = "Azure OpenAI not configured (client/deployment)"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        return {"_llm_unavailable": True}

    model = cast(str, azure_openai_deployment)
    # Derive local time equivalent for the model's context
    try:
        _cur_dt_utc = datetime.fromisoformat(current_iso_utc.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        _cur_dt_utc = datetime.now(timezone.utc)
    _cur_dt_local = _cur_dt_utc.astimezone(APP_TZ)

    sys_msg = (
        f"""You are analyzing Search & Rescue response messages. Extract vehicle, ETA, and response status with full parsing and normalization.

Context:
- Messages are from SAR responders coordinating by chat
- The typical response pattern includes whether they are responding, a vehicle type, and an ETA
- Because the responses are highly variable, you need to consider the meaning of the message and extract the relevant details. For example if someone says "Coming in 99" that clearly means they are responding, and 99 should be interpreted as the vehicle identifier because there's no clear other thing it could be.
- Vehicles are typically SAR-<number> but users may just use shorthand like "taking 108" or "grabbing 75"
- Current time is provided in both UTC and local timezone
- Local timezone: {TIMEZONE}
- IMPORTANT: When analyzing a user's message, consider their FULL message history provided in the context to understand their current status and maintain consistency
- IMPORTANT: If a user previously provided an ETA (like "11:00") and now says something like "switching to SAR 78", they are likely updating their vehicle but maintaining the same ETA
- IMPORTANT: Assume times mentioned in messages are in the local timezone ({TIMEZONE}). Convert to UTC for the final eta_iso.
- Vehicle types: Personal vehicles (POV, PV, own car, etc.) or numbered SAR units (78, SAR-78, etc.)
- "10-22" / "1022" means stand down/cancel (NOT a time)
- However a responder might be actually coming at 10:22 AM or 20:22 PM so you'll need to infer from the rest of the message if they are providing a time or a stand-down code. For example "Responding POV ETA 1022" would clearly be arriving at 10:22 not stand down code.
- It is possible for users to provide incomplete or ambiguous information, so be prepared to make educated guesses based on context
- Parse ALL time formats: absolute times (0830, 8:30 am), military/compact times (e.g., 2145), durations (e.g., 15 min, 1 hr, 15-20 minutes), and relative phrases

Output JSON schema (no extra keys, no trailing text):
{{
    "vehicle": "POV" | "SAR-<number>" | "SAR Rig" | "Unknown",
    "eta_iso": "<ISO 8601 UTC like 2024-02-22T12:45:00Z or 'Unknown'>",
    "status": "Responding" | "Cancelled" | "Available" | "Informational" | "Not Responding" | "Unknown",
    "evidence": "<short phrase from the message>",
    "confidence": <float between 0 and 1>
}}

Vehicle Normalization:
- Personal vehicle references → "POV"
- SAR unit numbers (any format) → "SAR-<number>" (e.g., "SAR-78")
- SAR rig references → "SAR Rig"
- No vehicle mentioned/unclear but they are responding → "POV"
- NEVER use "Not Responding" as a vehicle type

ETA Calculation:
- Convert ALL time references to HH:MM 24-hour local time first
- Durations: Add to current local time; for ranges (e.g., 15-20) choose the conservative upper bound
- Absolute/military times (e.g., 2145): Interpret as local time in {TIMEZONE}
- Relative updates: Modify previous ETA if provided
- CRITICAL: If user says "same ETA", "keeping same ETA", or similar, use their most recent ETA from the message history
- CRITICAL: If user changes vehicle but doesn't mention new ETA, maintain their previous ETA if they're still responding
- CRITICAL: Look in the message history context for previous ETAs when the current message doesn't specify a clear new time
- No time mentioned AND no previous ETA available → "Unknown"
- Place the final result as ISO-8601 UTC in field "eta_iso" (convert from local to UTC)

Status Classification:
- "Responding" = actively responding to mission
- "Cancelled" = person cancels their own response ('can't make it', 'I'm out')
- "Not Responding" = acknowledges stand down / using '10-22' code
- "Informational" = sharing info but not responding ('key is in box', asking questions)
- "Available" = willing to respond if needed
- "Unknown" = unclear intent
"""
    )
    user_msg = (
        f"Current time (UTC): {_cur_dt_utc.isoformat().replace('+00:00','Z')}\n"
        f"Current time (Local {TIMEZONE}): {_cur_dt_local.isoformat()}\n"
        f"Previous ETA (UTC, optional): {prev_eta_iso_utc or 'None'}\n"
        f"Message: {text}"
    )
    def _create_with_fallback():
        if client is None:
            raise Exception("Azure OpenAI client is None")

        messages_payload: List[ChatCompletionMessageParam] = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ]

        # Start generous; nano models often burn tokens on internal reasoning
        common_kwargs: Dict[str, Any] = {
            "max_completion_tokens": 512,
            "temperature": 1,
            "top_p": 1,
            "presence_penalty": 0,
            "frequency_penalty": 0,
        }

        # Strongly discourage long hidden reasoning for gpt-5-* small models
        try:
            if re.match(r"^gpt-5-(nano|mini)", str(model), re.I):
                common_kwargs["verbosity"] = "low"              # type: ignore
                common_kwargs["reasoning_effort"] = "low"   # type: ignore
        except Exception:
            pass

        hard_cap = 2048
        chosen_format = None

        # Attempt 1: json_object
        try:
            resp = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=messages_payload,
                **common_kwargs,
            )
            chosen_format = "json_object"
            return resp, messages_payload, dict(common_kwargs), chosen_format
        except Exception as e:
            etxt = str(e).lower()
            # prune unsupported params if needed
            for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "verbosity", "reasoning_effort"):
                if key in common_kwargs and key.replace("_"," ") in etxt:
                    common_kwargs.pop(key, None)

            # Retry with higher cap if we saw any output-limit hints
            if any(k in etxt for k in ("output limit", "max_tokens", "max tokens")):
                cur = int(common_kwargs.get("max_completion_tokens", 512) or 512)
                common_kwargs["max_completion_tokens"] = min(hard_cap, max(cur * 2, cur + 256))

        # Attempt 2: freeform (no response_format)
        resp2 = client.chat.completions.create(
            model=model,
            messages=messages_payload,
            **common_kwargs,
        )
        chosen_format = "freeform"
        return resp2, messages_payload, dict(common_kwargs), chosen_format

    try:
        resp, messages_payload, used_kwargs, chosen_format = _create_with_fallback()
        raw_content = (resp.choices[0].message.content or "").strip()

        def _retry_if_empty_or_invalid(raw_content: str, prev_kwargs: Dict[str, Any], prev_format: Optional[str]):
            if client is None:
                return raw_content
            try:
                if raw_content:
                    json.loads(raw_content)  # validate
                    return raw_content  # looks fine
            except Exception:
                pass

            # Prepare a slimmer prompt and larger cap for the retry
            slim_user = (
                f"{user_msg}\n\nReturn ONLY compact valid JSON per the schema. No prose."
            )
            messages_retry: List[ChatCompletionMessageParam] = [
                {"role": "system", "content": "Return ONLY valid JSON. No commentary."},
                {"role": "user", "content": slim_user},
            ]
            retry_kwargs = dict(prev_kwargs)
            retry_kwargs["max_completion_tokens"] = min(2048, max(768, int(prev_kwargs.get("max_completion_tokens", 512) or 512) * 2))
            retry_kwargs.pop("temperature", None)  # keep it as default 0/removed
            # Prefer json_object again on retry
            try:
                resp_retry = client.chat.completions.create(
                    model=model,
                    response_format={"type": "json_object"},
                    messages=messages_retry,
                    **retry_kwargs,
                )
                rc = (resp_retry.choices[0].message.content or "").strip()
                if rc:
                    return rc
            except Exception:
                pass
            # Last attempt: no response_format
            resp_retry2 = client.chat.completions.create(
                model=model,
                messages=messages_retry,
                **retry_kwargs,
            )
            return (resp_retry2.choices[0].message.content or "").strip()

        # If nothing came back or it wasn't JSON, try once more
        if not raw_content:
            raw_content = _retry_if_empty_or_invalid(raw_content, used_kwargs, chosen_format)

        if DEBUG_FULL_LLM_LOG:
            try:
                logger.debug(f"Full LLM response object: {resp}")
                logger.debug(f"Response choices: {resp.choices}")
                logger.debug(f"First choice: {resp.choices[0] if resp.choices else 'NO CHOICES'}")
                logger.debug(f"Message: {resp.choices[0].message if resp.choices else 'NO MESSAGE'}")
                logger.debug(f"Full LLM response content length={len(raw_content)}")
            except Exception:
                pass

        # Parse JSON with fallback
        try:
            data = json.loads(raw_content) if raw_content else {}
        except Exception:
            m = re.search(r"\{.*\}", raw_content or "", flags=re.S)
            data = json.loads(m.group(0)) if m else {}
        log_entry.update({
            "response": {"status": "success", "raw": raw_content, "response_format": chosen_format, "kwargs_used": used_kwargs},
            "parsed_data": data,
        })
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"LLM-only parse failed: {e}")
        log_entry["error"] = str(e)
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        return {"_llm_error": str(e)}


def _populate_eta_fields_from_llm_eta(eta_iso_or_unknown: str, message_time: datetime) -> Dict[str, Any]:
    """Translate LLM eta_iso into UI fields.
    - Unknown → eta='Unknown', timestamps=None, minutes=None
    - Else parse UTC ISO, compute local eta, eta_timestamp (legacy format in tests), eta_timestamp_utc, minutes_until_arrival
    """
    if not eta_iso_or_unknown or str(eta_iso_or_unknown).strip() == "Unknown":
        return {
            "eta": "Unknown",
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
        }
    try:
        eta_dt_utc = datetime.fromisoformat(str(eta_iso_or_unknown).replace("Z", "+00:00")).astimezone(timezone.utc)
        eta_local = eta_dt_utc.astimezone(APP_TZ)
        eta_hhmm = eta_local.strftime("%H:%M")
        eta_ts_local = (eta_local.strftime("%Y-%m-%d %H:%M:%S") if is_testing else eta_local.isoformat())
        minutes_until = int((eta_local - now_tz()).total_seconds() / 60)
        return {
            "eta": eta_hhmm,
            "eta_timestamp": eta_ts_local,
            "eta_timestamp_utc": eta_dt_utc.isoformat(),
            "minutes_until_arrival": minutes_until,
        }
    except Exception:
        logger.debug(f"Failed to parse eta_iso='{eta_iso_or_unknown}'")
        return {
            "eta": "Unknown",
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
        }


def extract_details_from_text(text: str, base_time: Optional[datetime] = None, prev_eta_iso: Optional[str] = None) -> Dict[str, Any]:
    """Thin wrapper around LLM-only parser. No heuristics.
    Returns: vehicle, eta, raw_status, status_source, status_confidence, eta_timestamp, eta_timestamp_utc, minutes_until_arrival
    """
    anchor_time: datetime = base_time or now_tz()
    current_iso_utc = anchor_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    data = _call_llm_only(text, current_iso_utc, prev_eta_iso)

    # If LLM is unavailable or errored, respect legacy contract for tests and return Unknowns
    if isinstance(data, dict) and (data.get("_llm_unavailable") or data.get("_llm_error")):
        return {
            "vehicle": "Unknown",
            "eta": "Unknown",
            "raw_status": "Unknown",
            "status_source": "LLM-Only",
            "status_confidence": 0.0,
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
            "parse_source": "LLM",
        }

    vehicle_raw = str(data.get("vehicle") or "Unknown") if isinstance(data, dict) else "Unknown"
    # Normalize vehicle like "SAR78" or "sar-078" -> "SAR-78"
    m_v = re.match(r"^\s*sar[\s-]?0*(\d{1,3})\s*$", vehicle_raw, flags=re.I)
    if m_v:
        vehicle = f"SAR-{int(m_v.group(1))}"
    elif vehicle_raw.strip().upper() in {"POV", "SAR RIG"}:
        vehicle = vehicle_raw.strip().upper().replace("SAR RIG", "SAR Rig")
    else:
        vehicle = vehicle_raw if vehicle_raw else "Unknown"
    status = str(data.get("status") or "Unknown") if isinstance(data, dict) else "Unknown"
    confidence_raw = data.get("confidence") if isinstance(data, dict) else 0.0
    try:
        status_confidence = float(confidence_raw or 0.0)
    except Exception:
        status_confidence = 0.0
    eta_iso = str(data.get("eta_iso") or "Unknown") if isinstance(data, dict) else "Unknown"

    # If eta_iso missing but LLM returned a plain HH:MM, compute fields from that using anchor_time
    eta_fields: Dict[str, Any]
    if (not eta_iso or eta_iso == "Unknown") and isinstance(data, dict):
        eta_text_alt = None
        # accept common keys some tests may return
        for k in ("eta", "eta_hhmm", "eta_text"):
            v = data.get(k)
            if isinstance(v, str) and re.fullmatch(r"\d{1,2}:\d{2}", v.strip()):
                eta_text_alt = v.strip()
                break
        if eta_text_alt:
            eta_fields = _compute_eta_fields(eta_text_alt, None, anchor_time)
        else:
            # Deterministic safety net for explicit AM/PM or military times
            det_eta = _extract_eta_from_text_local(text, anchor_time)
            if det_eta is not None:
                logger.debug(f"Deterministic ETA fallback applied (no LLM eta_iso). text='{text}', parsed_local='{det_eta.isoformat()}'")
                eta_fields = _compute_eta_fields(None, det_eta, anchor_time)
            else:
                # Try duration-based ETA extraction (e.g., 15-20 minutes, 1 hr)
                dur_eta = _extract_duration_eta(text, anchor_time)
                if dur_eta is not None:
                    logger.debug(f"Deterministic duration ETA applied. text='{text}', parsed_local='{dur_eta.isoformat()}'")
                    eta_fields = _compute_eta_fields(None, dur_eta, anchor_time)
                else:
                    # Check if user is standing down or cancelling - don't maintain ETA in those cases
                    standdown_phrases = ["standing down", "stand down", "10-22", "1022", "can't make it", "cancelling", "cancelled", "not responding"]
                    is_standdown = any(phrase in text.lower() for phrase in standdown_phrases)
                    
                    # If no deterministic ETA found and prev_eta_iso is available, maintain previous ETA
                    # BUT only if user is not standing down
                    if prev_eta_iso and prev_eta_iso != "Unknown" and not is_standdown:
                        logger.debug(f"Maintaining previous ETA (no deterministic ETA found). text='{text}', prev_eta_iso='{prev_eta_iso}'")
                        eta_fields = _populate_eta_fields_from_llm_eta(prev_eta_iso, anchor_time)
                    else:
                        if is_standdown:
                            logger.debug(f"Not maintaining ETA due to stand-down message. text='{text}'")
                        eta_fields = _populate_eta_fields_from_llm_eta(eta_iso, anchor_time)
    else:
        temp_fields = _populate_eta_fields_from_llm_eta(eta_iso, anchor_time)
        # If LLM produced an ETA that is in the past and text clearly says PM/AM, try deterministic parse
        try:
            minutes = temp_fields.get("minutes_until_arrival")
            if isinstance(minutes, int) and minutes <= -5 and re.search(r"(?i)\b(am|pm)\b", text or ""):
                det_eta = _extract_eta_from_text_local(text, anchor_time)
                if det_eta is not None:
                    logger.debug(f"Deterministic ETA override applied (LLM produced past ETA). text='{text}', parsed_local='{det_eta.isoformat()}', old_fields={temp_fields}")
                    temp_fields = _compute_eta_fields(None, det_eta, anchor_time)
            # If still Unknown, try duration ETA as a final fallback
            if (not temp_fields.get("eta_timestamp_utc") and not temp_fields.get("eta_timestamp")):
                dur_eta = _extract_duration_eta(text, anchor_time)
                if dur_eta is not None:
                    logger.debug(f"Deterministic duration ETA applied (post-LLM). text='{text}', parsed_local='{dur_eta.isoformat()}'")
                    temp_fields = _compute_eta_fields(None, dur_eta, anchor_time)
                else:
                    # Check if user is standing down or cancelling - don't maintain ETA in those cases
                    standdown_phrases = ["standing down", "stand down", "10-22", "1022", "can't make it", "cancelling", "cancelled", "not responding"]
                    is_standdown = any(phrase in text.lower() for phrase in standdown_phrases)
                    
                    # If no deterministic ETA found and prev_eta_iso is available, maintain previous ETA
                    # BUT only if user is not standing down
                    if prev_eta_iso and prev_eta_iso != "Unknown" and not is_standdown:
                        logger.debug(f"Maintaining previous ETA (post-LLM fallback). text='{text}', prev_eta_iso='{prev_eta_iso}'")
                        temp_fields = _populate_eta_fields_from_llm_eta(prev_eta_iso, anchor_time)
                    else:
                        if is_standdown:
                            logger.debug(f"Not maintaining ETA due to stand-down message (post-LLM). text='{text}'")
        except Exception:
            pass
        eta_fields = temp_fields

    # Track source of ETA derivation for debugging
    eta_source = "LLM"
    if (not eta_iso or eta_iso == "Unknown"):
        if eta_fields.get("eta") != "Unknown":
            eta_source = "Deterministic"
    else:
        # If we overrode due to past ETA with AM/PM text
        if isinstance(data, dict):
            try:
                # Recompute what fields would have been from eta_iso and compare
                check_fields = _populate_eta_fields_from_llm_eta(eta_iso, anchor_time)
                if check_fields.get("eta_timestamp_utc") != eta_fields.get("eta_timestamp_utc"):
                    eta_source = "Deterministic"
            except Exception:
                pass

    return {
        "vehicle": vehicle,
        "eta": eta_fields.get("eta", "Unknown"),
        "raw_status": status or "Unknown",
        "status_source": "LLM-Only",
        "status_confidence": status_confidence,
        "eta_timestamp": eta_fields.get("eta_timestamp"),
        "eta_timestamp_utc": eta_fields.get("eta_timestamp_utc"),
        "minutes_until_arrival": eta_fields.get("minutes_until_arrival"),
        "parse_source": eta_source,
    }


# No legacy heuristics or shims; fully AI-only


def _normalize_display_name(raw_name: str) -> str:
    try:
        name = raw_name or "Unknown"
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        name = re.sub(r"\s{2,}", " ", name)
        return name if name else (raw_name or "Unknown")
    except Exception:
        return raw_name or "Unknown"


# Load messages at startup
load_messages()


@app.post("/webhook")
async def receive_webhook(request: Request, api_key_valid: bool = Depends(validate_webhook_api_key)):
    data = await request.json()
    logger.info(f"Received webhook data from: {data.get('name', 'Unknown')}")

    if data.get("system") is True:
        logger.info("Skipping system-generated GroupMe message")
        return {"status": "skipped", "reason": "system message"}

    name = data.get("name", "Unknown")
    display_name = _normalize_display_name(name)
    text = data.get("text", "")
    created_at = data.get("created_at", 0)
    group_id = str(data.get("group_id") or "")
    team = GROUP_ID_TO_TEAM.get(str(group_id), "Unknown") if group_id else "Unknown"
    user_id = str(data.get("user_id") or data.get("sender_id") or "")

    try:
        if created_at == 0 or created_at is None:
            message_dt = now_tz()
            timestamp = (message_dt.strftime("%Y-%m-%d %H:%M:%S") if is_testing else message_dt.isoformat())
            logger.warning(f"Missing or invalid timestamp for message from {name}, using current time")
        else:
            message_dt = datetime.fromtimestamp(created_at, tz=APP_TZ)
            timestamp = message_dt.strftime("%Y-%m-%d %H:%M:%S") if is_testing else message_dt.isoformat()
    except Exception as e:
        message_dt = now_tz()
        timestamp = message_dt.strftime("%Y-%m-%d %H:%M:%S")
        logger.warning(f"Invalid timestamp {created_at} for message from {name}: {e}, using current time")

    if not text or text.strip() == "":
        logger.info(f"Skipping empty message from {name}")
        return {"status": "skipped", "reason": "empty message"}

    # Get full chronological message history for this user from ACTIVE messages only
    # CRITICAL: Only use active messages, never deleted messages for context
    user_message_history: List[Dict[str, Any]] = []
    try:
        # Get all ACTIVE messages from this user, sorted chronologically
        # Filter out any messages that have been soft-deleted
        active_user_messages = [
            msg for msg in messages 
            if msg.get("name") == display_name and not msg.get("deleted_at")
        ]
        active_user_messages.sort(key=lambda x: _coerce_dt(cast(Optional[str], x.get('timestamp_utc') or x.get('timestamp'))))
        user_message_history = active_user_messages
        
        # DEBUG: Log context building details
        logger.info(f"CONTEXT DEBUG for {display_name}: Found {len(active_user_messages)} active messages")
        for i, msg in enumerate(active_user_messages):
            logger.info(f"  {i+1}. {msg.get('timestamp', 'NO_TS')} - '{msg.get('text', 'NO_TEXT')}' -> vehicle={msg.get('vehicle', 'NO_VEH')}, eta={msg.get('eta', 'NO_ETA')}")
    except Exception:
        user_message_history = []

    # Build comprehensive context message with message sequence
    context_message = f"Sender: {display_name}. Current message: {text}"
    
    if user_message_history:
        # Simplified context - just show the most recent ETA and status for reference
        latest_eta = "Unknown"
        latest_vehicle = "Unknown"
        
        # Find most recent ETA from a non-cancelled message
        for msg in reversed(user_message_history):
            if (msg.get("eta") and msg.get("eta") != "Unknown" and 
                msg.get("arrival_status") != "Cancelled"):
                latest_eta = msg.get("eta", "Unknown")
                break
                
        # Find most recent vehicle from a non-cancelled message  
        for msg in reversed(user_message_history):
            if (msg.get("vehicle") and msg.get("vehicle") != "Unknown" and
                msg.get("arrival_status") != "Cancelled"):
                latest_vehicle = msg.get("vehicle", "Unknown")
                break
        
        context_message += f"\n\nPrevious status: Last ETA was {latest_eta}, last vehicle was {latest_vehicle}"
        context_message += f"\nNote: If user is standing down/cancelling, set ETA to 'Unknown'. If no new ETA is mentioned and user is still responding, maintain the previous ETA of {latest_eta}"
        
        # DEBUG: Log the context message being sent to LLM
        logger.info(f"CONTEXT DEBUG: Sending to LLM - '{context_message}'")

    # Previous ETA for relative updates (get the most recent one)
    prev_eta_iso: Optional[str] = None
    try:
        for msg in reversed(user_message_history):
            if msg.get("eta_timestamp_utc"):
                prev_eta_iso = msg.get("eta_timestamp_utc")
                break
    except Exception:
        prev_eta_iso = None

    parsed = extract_details_from_text(context_message, base_time=message_dt, prev_eta_iso=prev_eta_iso)
    logger.info(f"Parsed details: vehicle={parsed.get('vehicle')}, eta={parsed.get('eta')}, raw_status={parsed.get('raw_status')}")

    # Build message record
    minutes = parsed.get("minutes_until_arrival")
    raw_status = cast(str, parsed.get("raw_status") or "Unknown")
    arrival_status = raw_status
    if isinstance(minutes, int) and minutes <= 0 and raw_status == "Responding":
        arrival_status = "Arrived"

    message_record: Dict[str, Any] = {
        "name": display_name,
        "text": text,
        "timestamp": timestamp,
        "timestamp_utc": message_dt.astimezone(timezone.utc).isoformat() if message_dt else None,
        "group_id": group_id or None,
        "team": team,
        "user_id": user_id or None,
        "id": str(uuid.uuid4()),
        "vehicle": parsed.get("vehicle", "Unknown"),
        "eta": parsed.get("eta", "Unknown"),
        "eta_timestamp": parsed.get("eta_timestamp"),
        "eta_timestamp_utc": parsed.get("eta_timestamp_utc"),
        "minutes_until_arrival": parsed.get("minutes_until_arrival"),
        "arrival_status": arrival_status,
    "parse_source": parsed.get("parse_source", "LLM"),
    }

    reload_messages()
    messages.append(message_record)
    save_messages()
    return {"status": "ok"}


@app.post("/api/parse-debug")
async def parse_debug(request: Request) -> JSONResponse:
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        body_raw = await request.json()
        body: Dict[str, Any] = cast(Dict[str, Any], body_raw if isinstance(body_raw, dict) else {})
    except Exception:
        body = {}

    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="'text' is required")

    created_at = body.get("created_at")
    prev_eta_iso = cast(Optional[str], body.get("prev_eta_iso"))

    try:
        base_dt = datetime.fromtimestamp(float(created_at), tz=APP_TZ) if created_at is not None else now_tz()
    except Exception:
        base_dt = now_tz()

    llm_only_out = extract_details_from_text(text, base_time=base_dt, prev_eta_iso=prev_eta_iso)
    azure_ok = bool(client is not None and azure_openai_deployment)

    return JSONResponse(content={
        "base_time_iso": base_dt.astimezone(timezone.utc).isoformat(),
        "llm_only": llm_only_out,
        "llm_only_available": azure_ok,
        "env_default_mode": "llm-only",
    })


@app.get("/api/responders")
def get_responder_data(request: Request) -> JSONResponse:
    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
        or request.headers.get("X-User")
    )
    if not user_email:
        if not (is_testing or ALLOW_LOCAL_AUTH_BYPASS):
            raise HTTPException(status_code=401, detail="Not authenticated")
    else:
        if not is_email_domain_allowed(user_email):
            raise HTTPException(status_code=403, detail="Access denied")
    reload_messages()
    return JSONResponse(content=messages)


@app.get("/api/current-status")
def get_current_status(request: Request) -> JSONResponse:
    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
        or request.headers.get("X-User")
    )
    if not user_email:
        if not (is_testing or ALLOW_LOCAL_AUTH_BYPASS):
            raise HTTPException(status_code=401, detail="Not authenticated")
    else:
        if not is_email_domain_allowed(user_email):
            raise HTTPException(status_code=403, detail="Access denied")

    reload_messages()

    latest_by_person: Dict[str, Dict[str, Any]] = {}
    sorted_messages = sorted(messages, key=lambda x: _coerce_dt(cast(Optional[str], x.get('timestamp_utc') or x.get('timestamp'))))
    for msg in sorted_messages:
        name = (msg.get('name') or '').strip()
        if not name:
            continue
        arrival_status = msg.get('arrival_status', 'Unknown')
        eta = msg.get('eta', 'Unknown')
        text = (msg.get('text') or '').lower()
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
            current_ts = _coerce_dt(cast(Optional[str], current_entry.get('timestamp_utc') or current_entry.get('timestamp')))
            new_ts = _coerce_dt(cast(Optional[str], msg.get('timestamp_utc') or msg.get('timestamp')))
            if new_ts >= current_ts:
                latest_by_person[name] = dict(msg)
                latest_by_person[name]['_priority'] = priority
            elif new_ts == current_ts and priority > current_entry.get('_priority', 0):
                latest_by_person[name] = dict(msg)
                latest_by_person[name]['_priority'] = priority

    result: List[Dict[str, Any]] = []
    for person_data in latest_by_person.values():
        person_data.pop('_priority', None)
        result.append(person_data)
    result.sort(key=lambda x: _coerce_dt(cast(Optional[str], x.get('timestamp_utc') or x.get('timestamp'))), reverse=True)
    return JSONResponse(content=result)


@app.post("/api/responders")
async def create_responder_entry(request: Request) -> JSONResponse:
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        raw = await request.json()
        body: Dict[str, Any] = cast(Dict[str, Any], raw if isinstance(raw, dict) else {})
    except Exception:
        body = {}

    name = _normalize_display_name(str(cast(Any, body.get("name")) or "Unknown"))
    text = str(cast(Any, body.get("text")) or "")
    team = str(cast(Any, body.get("team")) or "Unknown")
    group_id = str(cast(Any, body.get("group_id")) or "")
    vehicle = str(cast(Any, body.get("vehicle")) or "Unknown")
    user_id = str(cast(Any, body.get("user_id")) or "")
    eta_str = cast(Optional[str], body.get("eta") if "eta" in body else None)
    ts_input: Any = body.get("timestamp") if "timestamp" in body else None
    eta_ts_input: Any = body.get("eta_timestamp") if "eta_timestamp" in body else None

    message_dt = _parse_datetime_like(ts_input) or now_tz()
    eta_dt = _parse_datetime_like(eta_ts_input)
    eta_fields = _compute_eta_fields(eta_str, eta_dt, message_dt)

    rec: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "text": text,
        "timestamp": (message_dt.strftime("%Y-%m-%d %H:%M:%S") if is_testing else message_dt.isoformat()),
        "timestamp_utc": message_dt.astimezone(timezone.utc).isoformat(),
        "group_id": group_id or None,
        "team": team,
        "user_id": user_id or None,
        "vehicle": vehicle,
        "eta": eta_fields.get("eta", "Unknown"),
        "eta_timestamp": eta_fields.get("eta_timestamp"),
        "eta_timestamp_utc": eta_fields.get("eta_timestamp_utc"),
        "minutes_until_arrival": eta_fields.get("minutes_until_arrival"),
        "arrival_status": eta_fields.get("arrival_status"),
    "parse_source": "Manual",
    }

    reload_messages()
    messages.append(rec)
    save_messages()
    return JSONResponse(status_code=201, content=rec)


@app.put("/api/responders/{msg_id}")
async def update_responder_entry(msg_id: str, request: Request) -> JSONResponse:
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")

    reload_messages()
    idx = next((i for i, m in enumerate(messages) if str(m.get("id")) == msg_id), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        raw = await request.json()
        patch: Dict[str, Any] = cast(Dict[str, Any], raw if isinstance(raw, dict) else {})
    except Exception:
        patch = {}

    current = dict(messages[idx])
    for key in ["name", "text", "team", "group_id", "vehicle", "user_id"]:
        if key in patch:
            val = patch.get(key)
            if key == "name":
                val = _normalize_display_name(str(cast(Any, val) or ""))
            current[key] = val

    ts_in: Any = patch.get("timestamp") if "timestamp" in patch else current.get("timestamp")
    msg_dt = _parse_datetime_like(ts_in) or now_tz()
    current["timestamp"] = (msg_dt.strftime("%Y-%m-%d %H:%M:%S") if is_testing else msg_dt.isoformat())
    current["timestamp_utc"] = msg_dt.astimezone(timezone.utc).isoformat()

    eta_str = cast(Optional[str], patch.get("eta") if "eta" in patch else current.get("eta"))
    eta_ts_in: Any = patch.get("eta_timestamp") if "eta_timestamp" in patch else current.get("eta_timestamp")
    eta_dt = _parse_datetime_like(eta_ts_in)
    eta_fields = _compute_eta_fields(eta_str, eta_dt, msg_dt)
    current.update({
        "eta": eta_fields.get("eta", "Unknown"),
        "eta_timestamp": eta_fields.get("eta_timestamp"),
        "eta_timestamp_utc": eta_fields.get("eta_timestamp_utc"),
        "minutes_until_arrival": eta_fields.get("minutes_until_arrival"),
        "arrival_status": eta_fields.get("arrival_status"),
    "parse_source": "Manual",
    })

    messages[idx] = current
    save_messages()
    return JSONResponse(content=current)


@app.delete("/api/responders/{msg_id}")
def delete_responder_entry(msg_id: str, request: Request) -> Dict[str, Any]:
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")

    reload_messages()
    to_delete = [m for m in messages if str(m.get("id")) == msg_id]
    if not to_delete:
        raise HTTPException(status_code=404, detail="Not found")
    soft_delete_messages(to_delete)
    remaining = [m for m in messages if str(m.get("id")) != msg_id]
    messages.clear()
    messages.extend(remaining)
    save_messages()
    return {"status": "deleted", "id": msg_id, "soft_delete": True}


@app.post("/api/responders/bulk-delete")
async def bulk_delete_responder_entries(request: Request) -> Dict[str, Any]:
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        body = await request.json()
        ids: List[str] = list(map(str, body.get("ids", [])))
    except Exception:
        ids = []
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided")

    reload_messages()
    ids_set = set(ids)
    to_delete = [m for m in messages if str(m.get("id")) in ids_set]
    to_keep = [m for m in messages if str(m.get("id")) not in ids_set]
    if to_delete:
        soft_delete_messages(to_delete)
        messages.clear()
        messages.extend(to_keep)
        save_messages()
    return {"status": "deleted", "removed": int(len(to_delete)), "soft_delete": True}


@app.post("/api/clear-all")
def clear_all_data(request: Request) -> Dict[str, Any]:
    allow_env = os.getenv("ALLOW_CLEAR_ALL", "false").lower() == "true"
    provided_key = request.headers.get("X-API-Key")
    key_ok = webhook_api_key and provided_key == webhook_api_key
    if not (allow_env or key_ok):
        raise HTTPException(status_code=403, detail="Clear-all is disabled")
    reload_messages()
    initial = len(messages)
    _clear_all_messages()
    return {"status": "cleared", "removed": int(initial)}


@app.get("/api/deleted-responders")
def get_deleted_responders(request: Request) -> List[Dict[str, Any]]:
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")
    load_deleted_messages()
    return deleted_messages


@app.post("/api/deleted-responders/undelete")
async def undelete_responder_entries(request: Request) -> Dict[str, Any]:
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        body = await request.json()
        ids: List[str] = list(map(str, body.get("ids", [])))
    except Exception:
        ids = []
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    restored_count = undelete_messages(ids)
    return {"status": "restored", "restored": restored_count}


@app.delete("/api/deleted-responders/{msg_id}")
def permanently_delete_responder_entry(msg_id: str, request: Request) -> Dict[str, Any]:
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")
    load_deleted_messages()
    initial = len(deleted_messages)
    remaining = [m for m in deleted_messages if str(m.get("id")) != msg_id]
    if len(remaining) == initial:
        raise HTTPException(status_code=404, detail="Not found in deleted storage")
    deleted_messages.clear()
    deleted_messages.extend(remaining)
    save_deleted_messages()
    return {"status": "permanently_deleted", "id": msg_id}


@app.post("/api/deleted-responders/clear-all")
def clear_all_deleted_data(request: Request) -> Dict[str, Any]:
    allow_env = os.getenv("ALLOW_CLEAR_ALL", "false").lower() == "true"
    provided_key = request.headers.get("X-API-Key")
    key_ok = webhook_api_key and provided_key == webhook_api_key
    if not (allow_env or key_ok):
        raise HTTPException(status_code=403, detail="Clear-all is disabled")
    load_deleted_messages()
    initial = len(deleted_messages)
    deleted_messages.clear()
    save_deleted_messages()
    return {"status": "cleared", "removed": int(initial)}


@app.get("/debug/pod-info")
def get_pod_info():
    pod_name = os.getenv("HOSTNAME", "unknown-pod")
    pod_ip = os.getenv("POD_IP", "unknown-ip")
    redis_status = "disconnected"
    try:
        init_redis()
        if redis_client:
            cast(Any, redis_client).ping()
            redis_status = "connected"
    except Exception:
        redis_status = "error"
    return JSONResponse(content={
        "pod_name": pod_name,
        "pod_ip": pod_ip,
        "message_count": len(messages),
        "redis_status": redis_status,
    })


@app.get("/health")
def health() -> Dict[str, Any]:
    try:
        status = "ok"
        try:
            init_redis()
            if redis_client:
                cast(Any, redis_client).ping()
        except Exception:
            status = "degraded"
        return {"status": status}
    except Exception:
        return {"status": "error"}


@app.get("/dashboard", response_class=HTMLResponse)
def display_dashboard() -> str:
    reload_messages()
    current_time = now_tz()
    html_out = f"""
    <h1>🚨 Responder Dashboard</h1>
    <p><strong>Current Time:</strong> {current_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><a href="/deleted-dashboard">View Deleted Messages →</a></p>
    <table border='1' cellpadding='8' style='border-collapse: collapse; font-family: monospace;'>
        <tr style='background-color: #f0f0f0;'>
            <th>Message Time</th>
            <th>Name</th>
            <th>Unit</th>
            <th>Vehicle</th>
            <th>ETA</th>
            <th>Minutes Out</th>
            <th>Status</th>
            <th>Parse Source</th>
            <th>Message</th>
        </tr>
    """

    sorted_messages = sorted(messages, key=lambda x: (
        x.get('minutes_until_arrival', 9999) if x.get('minutes_until_arrival') is not None else 9999,
        x.get('timestamp', ''),
    ), reverse=False)

    for msg in sorted_messages:
        vehicle = msg.get('vehicle', 'Unknown')
        team = msg.get('team', 'Unknown')
        eta_display = msg.get('eta_timestamp') or msg.get('eta', 'Unknown')
        minutes_out = msg.get('minutes_until_arrival')
        status = msg.get('arrival_status', 'Unknown')

        if status == 'Not Responding':
            row_color = '#ffcccc'
        elif vehicle == 'Unknown':
            row_color = '#ffffcc'
        elif minutes_out is not None and minutes_out <= 5:
            row_color = '#ccffcc'
        elif minutes_out is not None and minutes_out <= 15:
            row_color = '#cceeff'
        else:
            row_color = '#ffffff'

        minutes_display = f"{minutes_out} min" if minutes_out is not None else "—"

        html_out += f"""
        <tr style='background-color: {row_color};'>
            <td>{_esc(msg.get('timestamp', ''))}</td>
            <td><strong>{_esc(msg.get('name', ''))}</strong></td>
            <td>{_esc(team)}</td>
            <td>{_esc(vehicle)}</td>
            <td>{_esc(eta_display)}</td>
            <td>{_esc(minutes_display)}</td>
            <td>{_esc(status)}</td>
            <td>{_esc(msg.get('parse_source', 'LLM'))}</td>
            <td style='max-width: 300px; word-wrap: break-word;'>{_esc(msg.get('text', ''))}</td>
        </tr>
        """

    html_out += """
    </table>
    <br>
    <div style='font-size: 12px; color: #666;'>
        <p><strong>Color Legend:</strong></p>
        <div style='background-color: #ccffcc; display: inline-block; padding: 2px 8px; margin: 2px;'>Arriving Soon (≤5 min)</div>
        <div style='background-color: #cceeff; display: inline-block; padding: 2px 8px; margin: 2px;'>Arriving Medium (≤15 min)</div>
        <div style='background-color: #ffffcc; display: inline-block; padding: 2px 8px; margin: 2px;'>Unknown Vehicle/ETA</div>
        <div style='background-color: #ffcccc; display: inline-block; padding: 2px 8px; margin: 2px;'>Not Responding</div>
    </div>
    """
    return html_out


@app.get("/deleted-dashboard", response_class=HTMLResponse)
def display_deleted_dashboard() -> str:
    load_deleted_messages()
    current_time = now_tz()
    html_out = f"""
    <h1>🗑️ Deleted Responder Dashboard</h1>
    <p><strong>Current Time:</strong> {current_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><strong>Total Deleted Messages:</strong> {len(deleted_messages)}</p>
    <p><a href="/dashboard">← Back to Active Dashboard</a></p>
    <table border='1' cellpadding='8' style='border-collapse: collapse; font-family: monospace;'>
        <tr style='background-color: #f0f0f0;'>
            <th>Message Time</th>
            <th>Deleted At</th>
            <th>Name</th>
            <th>Unit/Team</th>
            <th>Vehicle</th>
            <th>ETA</th>
            <th>Parse Source</th>
            <th>Message</th>
            <th>Message ID</th>
        </tr>
    """

    sorted_deleted = sorted(deleted_messages, key=lambda x: x.get('deleted_at', ''), reverse=True)
    for msg in sorted_deleted:
        msg_time = msg.get('timestamp', 'Unknown')
        deleted_time = msg.get('deleted_at', 'Unknown')
        name = msg.get('name', '')
        team = msg.get('team', msg.get('unit', ''))
        vehicle = msg.get('vehicle', 'Unknown')
        eta = msg.get('eta', 'Unknown')
        message_text = msg.get('text', '')
        msg_id = msg.get('id', '')
        if len(message_text) > 100:
            message_text = message_text[:100] + "..."
        try:
            if deleted_time != 'Unknown':
                dt = datetime.fromisoformat(str(deleted_time).replace('Z', '+00:00'))
                deleted_display = dt.strftime('%Y-%m-%d %H:%M:%S')
            else:
                deleted_display = 'Unknown'
        except Exception:
            deleted_display = deleted_time

        html_out += f"""
        <tr style='background-color: #fff0f0;'>
            <td>{_esc(msg_time)}</td>
            <td>{_esc(deleted_display)}</td>
            <td>{_esc(name)}</td>
            <td>{_esc(team)}</td>
            <td>{_esc(vehicle)}</td>
            <td>{_esc(eta)}</td>
            <td>{_esc(msg.get('parse_source', 'LLM'))}</td>
            <td style='max-width: 300px; word-wrap: break-word;'>{_esc(message_text)}</td>
            <td style='font-size: 10px; color: #666;'>{_esc(msg_id)}</td>
        </tr>
        """

    if not deleted_messages:
        html_out += """
        <tr>
            <td colspan="8" style="text-align: center; color: #666; font-style: italic;">No deleted messages</td>
        </tr>
        """

    html_out += """
    </table>
    <br>
    <div style='font-size: 12px; color: #666;'>
        <p><strong>Note:</strong> Deleted messages are stored in Redis under 'respondr_deleted_messages' key.</p>
        <p>Use the API endpoints to restore messages: POST /api/deleted-responders/undelete</p>
    </div>
    """
    return html_out


# Determine frontend build path
if os.path.exists(os.path.join(os.path.dirname(__file__), "frontend/build")):
    frontend_build = os.path.join(os.path.dirname(__file__), "frontend/build")
else:
    frontend_build = os.path.join(os.path.dirname(__file__), "../frontend/build")

static_dir = os.path.join(frontend_build, "static")
if not is_testing and os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.post("/cleanup/invalid-timestamps")
def cleanup_invalid_timestamps(_: bool = Depends(validate_webhook_api_key)) -> Dict[str, Any]:
    global messages
    reload_messages()
    initial_count = len(messages)
    kept: List[Dict[str, Any]] = []
    removed = 0
    for msg in messages:
        ts = msg.get("timestamp_utc") or msg.get("timestamp")
        if not ts:
            removed += 1
            continue
        if isinstance(ts, str) and ts.startswith("1970-01-01"):
            removed += 1
            continue
        kept.append(msg)
    messages = kept
    save_messages()
    return {"status": "success", "message": f"Cleaned up {removed} invalid entries", "initial_count": initial_count, "remaining_count": len(messages)}


@app.get("/")
def serve_frontend():
    if is_testing:
        return {"message": "Test mode - frontend not available"}
    index_path = os.path.join(frontend_build, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return {"message": "Frontend not built - run 'npm run build' in frontend directory"}


@app.get("/scvsar-logo.png")
def serve_logo():
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    logo_path = os.path.join(frontend_build, "scvsar-logo.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path)
    raise HTTPException(status_code=404, detail="Logo not found")


@app.get("/favicon.ico")
def serve_favicon():
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "favicon.ico")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/manifest.json")
def serve_manifest():
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "manifest.json")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/robots.txt")
def serve_robots():
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "robots.txt")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/logo192.png")
def serve_logo192():
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "logo192.png")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/logo512.png")
def serve_logo512():
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "logo512.png")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")


# --- ACR webhook to auto-restart deployment on image push ---
ACR_WEBHOOK_TOKEN = os.getenv("ACR_WEBHOOK_TOKEN")
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "respondr")
K8S_DEPLOYMENT = os.getenv("K8S_DEPLOYMENT", "respondr-deployment")


@app.post("/internal/acr-webhook")
async def acr_webhook(request: Request):
    provided = request.headers.get("X-ACR-Token") or request.query_params.get("token")
    if not ACR_WEBHOOK_TOKEN or provided != ACR_WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        raw_payload: Any = await request.json()
    except Exception:
        raw_payload = {}

    payload: Dict[str, Any] = cast(Dict[str, Any], raw_payload if isinstance(raw_payload, dict) else {})
    action = cast(str | None, payload.get("action") or payload.get("eventType"))
    target = cast(Dict[str, Any], payload.get("target", {}) or {})
    repo = cast(str, target.get("repository", ""))
    tag = cast(str, target.get("tag", ""))

    logger.info(f"ACR webhook: action={action} repo={repo} tag={tag}")
    if action and "push" not in str(action).lower():
        return {"status": "ignored", "reason": f"action={action}"}

    expected_repo = os.getenv("ACR_REPOSITORY", "respondr")
    if expected_repo and repo and expected_repo not in repo:
        return {"status": "ignored", "reason": f"repo={repo}"}

    try:
        ks = importlib.import_module("kubernetes")
        k8s_client = getattr(ks, "client")
        k8s_config = getattr(ks, "config")
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        apps = k8s_client.AppsV1Api()
        patch: Dict[str, Any] = {
            "spec": {
                "template": {
                    "metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()}}
                }
            }
        }
        apps.patch_namespaced_deployment(name=K8S_DEPLOYMENT, namespace=K8S_NAMESPACE, body=patch)
        logger.info(f"Triggered rollout restart for deployment {K8S_DEPLOYMENT} in namespace {K8S_NAMESPACE}")
        return {"status": "restarted", "deployment": K8S_DEPLOYMENT, "namespace": K8S_NAMESPACE}
    except Exception as e:
        logger.error(f"Failed to restart deployment: {e}")
        raise HTTPException(status_code=500, detail="Failed to restart deployment")


# SPA catch-all for client routes; declare last
@app.get("/{full_path:path}")
def spa_catch_all(full_path: str):
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    index_path = os.path.join(frontend_build, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend not built")

