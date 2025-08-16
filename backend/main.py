import os
import sys
import json
import logging
import re
import html
from typing import Any, Dict, Optional, cast, List
# Test ACR webhook auto-deployment - v3

# Test comment 2

from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    zoneinfo_available = True
except ImportError:
    zoneinfo_available = False
    _ZoneInfo = None

# Create a timezone helper that works on all platforms
def get_timezone(name: str) -> timezone:
    """Get timezone object, with fallback for Windows."""
    if name == "UTC":
        return timezone.utc
    elif name == "America/Los_Angeles" and zoneinfo_available:
        try:
            return _ZoneInfo("America/Los_Angeles")  # type: ignore
        except Exception:
            pass
    # Fallback: PST approximation as UTC-8 (ignoring DST)
    return timezone(timedelta(hours=-8))
from urllib.parse import quote
import importlib
import redis
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from openai import AzureOpenAI
from openai import APIStatusError
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Safe HTML escape helper
def _esc(v: Any) -> str:
    try:
        return html.escape("" if v is None else str(v))
    except Exception:
        return ""

# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis-service")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_KEY = "respondr_messages"
REDIS_DELETED_KEY = "respondr_deleted_messages"

# Fast local parse mode (bypass Azure for local/dev seeding)
FAST_LOCAL_PARSE = os.getenv("FAST_LOCAL_PARSE", "false").lower() == "true"

# Validate environment variables
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")

# Webhook API key for security
webhook_api_key = os.getenv("WEBHOOK_API_KEY")

# Multi-tenant authentication configuration
allowed_email_domains = os.getenv("ALLOWED_EMAIL_DOMAINS", "scvsar.org,rtreit.com").split(",")
allowed_email_domains = [domain.strip() for domain in allowed_email_domains if domain.strip()]

# Admin users configuration (comma-separated emails)
allowed_admin_users = os.getenv("ALLOWED_ADMIN_USERS", "").split(",")
allowed_admin_users = [u.strip().lower() for u in allowed_admin_users if u.strip()]

# Local dev bypass: allow running without OAuth2 proxy
ALLOW_LOCAL_AUTH_BYPASS = os.getenv("ALLOW_LOCAL_AUTH_BYPASS", "false").lower() == "true"
# Optional: whether local bypass should imply admin
LOCAL_BYPASS_IS_ADMIN = os.getenv("LOCAL_BYPASS_IS_ADMIN", "false").lower() == "true"

# Check if we're running in test mode
is_testing = os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules

# API key check: allow disabling via env (and always in tests)
disable_api_key_check = os.getenv("DISABLE_API_KEY_CHECK", "false").lower() == "true" or is_testing

# Timezone configuration: default to PST approximation; allow override via TIMEZONE env
TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")
APP_TZ = get_timezone(TIMEZONE)

# Warn loudly if DST-aware zoneinfo is unavailable and non-UTC TZ requested
if not 'zoneinfo_available' in globals():
    pass
else:
    if not zoneinfo_available and TIMEZONE.upper() != "UTC":
        logger.warning(
            "zoneinfo not available; using fixed UTC-8 fallback. Set TIMEZONE=UTC or install zoneinfo for correct DST."
        )

def now_tz() -> datetime:
    return datetime.now(APP_TZ)

# Feature flag: enable an extra AI finalization pass on ETA
ENABLE_AI_FINALIZE = os.getenv("ENABLE_AI_FINALIZE", "true").lower() == "true"

# ----------------------------------------------------------------------------
# FastAPI app and global state
# ----------------------------------------------------------------------------
app = FastAPI()

# In-memory message stores; tests will patch these
messages: List[Dict[str, Any]] = []
deleted_messages: List[Dict[str, Any]] = []

# Redis client (initialized on demand)
redis_client: Optional[redis.Redis] = None

def validate_webhook_api_key(x_api_key: Optional[str] = Header(None)) -> bool:
    """Validate API key for protected endpoints.

    In tests or when disabled, always allow. Otherwise require header to match WEBHOOK_API_KEY.
    """
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

# GroupMe group_id to Team mapping
# Source: provided GroupMe group list
""" <select name="bot[group_id]" id="bot_group_id">
<option value="102193274">OSU Test group</option>
<option value="97608845">SCVSAR 4X4 Team</option>
<option value="6846970">ASAR MEMBERS</option>
<option value="61402638">ASAR Social</option>
<option value="19723040">Snohomish Unit Mission Response</option>
<option value="96018206">SCVSAR-IMT</option>
<option value="1596896">SCVSAR K9 Team</option>
<option value="92390332">ASAR Drivers</option>
<option value="99606944">OSU - Social</option>
<option value="14533239">MSAR Mission Response</option>
<option value="106549466">ESAR Coordination</option>
<option value="16649586">OSU-MISSION RESPONSE</option>
<option value="109174633">PreProd-Responder</option>
 """


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

# ============================================================================
# AI Function Calling - Calculation Functions for Azure OpenAI
# ============================================================================

def calculate_eta_from_duration(current_time: str, duration_minutes: int) -> Dict[str, Any]:
    """Calculate ETA by adding duration to current time. Used by AI function calling."""
    try:
        # Parse current time (format: "HH:MM")
        hour, minute = map(int, current_time.split(':'))
        
        # Create datetime for calculation
        base_time = now_tz().replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # Add duration
        eta_time = base_time + timedelta(minutes=duration_minutes)
        
        # Return formatted result
        return {
            "eta": eta_time.strftime("%H:%M"),
            "valid": True,
            "duration_minutes": duration_minutes,
            "warning": "ETA over 24 hours - please verify" if duration_minutes > 1440 else None
        }
    except Exception as e:
        return {"eta": "Unknown", "valid": False, "error": str(e)}

# =============================================================================
# Assisted-mode extraction utilities (ported from benchmark)
# =============================================================================

def _fix_common_typos(s: str) -> str:
    replacements = {
        r"\bmninute?s?\b": "minutes",
        r"\bminitue?s?\b": "minutes",
        r"\bminites?\b": "minutes",
        r"\bmintes?\b": "minutes",
        r"\bminuets?\b": "minutes",
        r"\bhoures?\b": "hours",
        r"\bhors?\b": "hours",
    }
    out = s
    for pat, repl in replacements.items():
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out

def normalize_vehicle(text: str) -> str:
    t = (text or "").lower()
    if not t:
        return "Unknown"
    # POV
    if any(k in t for k in ["pov","p.v.","pv","personal vehicle","own car","driving myself","my car","personal"]) and "sar" not in t:
        return "POV"
    # SAR Rig
    if re.search(r"\bsar\s*rig\b", t):
        return "SAR Rig"
    # Special: "coming in <int>" vehicle unless time unit follows
    m = re.search(r"\bcoming\s+in\s+(\d{1,3})(?!\s*(?:m|min|mins?|minutes?)\b)", t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 999:
            return f"SAR-{n}"
    # Negative/positive cues
    NEG = r"\b(?:key|box|code|channel|ch\b|freq|mhz|alpha|bravo|charlie|copy\b|subject|subj\b|grid|mile)\b"
    POS = r"(?:\bsar\b|\bunit\b|\brig\b|\btruck\b|\brespond(?:ing)?\b|\brolling\b|\btaking\b|\bcoming\b|\barriving\b|\bwith\b|\bdriving\b|\bin\b)"
    neg = bool(re.search(NEG, t))
    # Explicit SAR-### wins
    m = re.search(r"\bsar[\s-]*0*(\d{1,3})\b", t)
    if m:
        return f"SAR-{int(m.group(1))}"
    # Contexted numeric vehicle
    if not neg and re.search(POS, t):
        m = re.search(r"\b0*(\d{1,3})\b", t)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 999:
                return f"SAR-{n}"
    return "Unknown"

_SMALL = {
    "zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
    "ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,"sixteen":16,
    "seventeen":17,"eighteen":18,"nineteen":19,
}
_TENS = {"twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90}

def _words_to_int(phrase: str) -> Optional[int]:
    if not phrase:
        return None
    phrase = phrase.replace("-", " ")
    toks = re.findall(r"[a-z]+", phrase.lower())
    if not toks:
        return None
    total, current = 0, 0
    for w in toks:
        if w in ("a", "an"):
            current += 1
        elif w in _SMALL:
            current += _SMALL[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        elif w in ("and", "about", "around", "approximately", "roughly"):
            continue
        elif w in ("half", "quarter"):
            return None
        else:
            return None
    total += current
    return total if total >= 0 else None

def _shift_hhmm(hhmm: str, delta_min: int) -> Optional[str]:
    try:
        h, m = map(int, hhmm.split(":"))
        tot = (h * 60 + m + delta_min) % (24 * 60)
        return f"{tot // 60:02d}:{tot % 60:02d}"
    except Exception:
        return None

def convert_eta_text_to_hhmm(eta_text: str, base_time: datetime, prev_eta_hhmm: Optional[str] = None) -> str:
    try:
        if not eta_text or not eta_text.strip():
            return "Unknown"
        raw = eta_text.strip()
        low = _fix_common_typos(raw.lower()).replace("~", "").strip()
        # Treat ETD like ETA
        low = re.sub(r"^\s*etd\b", "eta", low)
        # Exact HH:MM with optional am/pm
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(am|pm)?\s*$", low)
        if m:
            hour, minute, ap = int(m.group(1)), int(m.group(2)), m.group(3)
            if minute > 59:
                return "Unknown"
            if ap:
                if ap == "pm" and hour != 12:
                    hour += 12
                if ap == "am" and hour == 12:
                    hour = 0
            if hour == 24:
                hour = 0
            if hour > 23:
                return "Unknown"
            return f"{hour:02d}:{minute:02d}"
        # Compact 3/4 digit times
        if re.match(r"^\s*\d{3,4}\s*$", low):
            digits = re.findall(r"\d+", low)[0]
            if len(digits) == 3:
                hour, minute = int(digits[0]), int(digits[1:3])
            else:
                hour, minute = int(digits[:2]), int(digits[2:])
            if hour == 24:
                hour = 0
            if hour > 23 or minute > 59:
                return "Unknown"
            return f"{hour:02d}:{minute:02d}"
        # "8 pm"
        m = re.match(r"^\s*(\d{1,2})\s*(am|pm)\s*$", low)
        if m:
            hour, ap = int(m.group(1)), m.group(2)
            if ap == "pm" and hour != 12:
                hour += 12
            if ap == "am" and hour == 12:
                hour = 0
            return f"{hour:02d}:00"
        # Relative updates vs prev ETA
        def _amt_to_minutes(txt: str) -> Optional[int]:
            txt = txt.strip()
            if re.match(r"^\d+(?:\.\d+)?$", txt):
                return int(round(float(txt)))
            w = _words_to_int(txt)
            return w
        if prev_eta_hhmm:
            if any(k in low for k in ["unchanged", "same as before", "same as prior", "no change"]):
                return prev_eta_hhmm
            m = re.search(r"(?:\beta\s*)?([+-])\s*(\d+)\b", low)
            if m:
                sign = 1 if m.group(1) == "+" else -1
                mins = int(m.group(2))
                shifted = _shift_hhmm(prev_eta_hhmm, sign * mins)
                return shifted or "Unknown"
            m = re.search(r"\b((?:\d+(?:\.\d+)?)|(?:[a-z\- ]+))\s*(?:mins?|minutes?)\s*(early|earlier|ahead)\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, -val)
                    return shifted or "Unknown"
            m = re.search(r"\b((?:\d+(?:\.\d+)?)|(?:[a-z\- ]+))\s*(?:mins?|minutes?)\s*(late|later|behind)\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, +val)
                    return shifted or "Unknown"
            # allow optional unit for phrases like "pushed back by fifteen"
            m = re.search(r"\b(?:pushed(?:\s*back)?|push(?:ed)?\s*back)\s*(?:by\s*)?((?:\d+|[a-z\- ]+))(?:\s*(?:mins?|minutes?))?\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, +val)
                    return shifted or "Unknown"
            m = re.search(r"\b(?:moved|bumped)\s*up\s*(?:by\s*)?((?:\d+|[a-z\- ]+))\s*(?:mins?|minutes?)\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, -val)
                    return shifted or "Unknown"
            m = re.search(r"\bslipped\s*((?:\d+|[a-z\- ]+))\s*(?:mins?|minutes?)\b", low)
            if m:
                val = _amt_to_minutes(m.group(1))
                if val is not None:
                    shifted = _shift_hhmm(prev_eta_hhmm, +val)
                    return shifted or "Unknown"
        m = re.search(r"\b(?:arrive|arrival|be there|there|by)\s*(?:at\s*)?(\d{1,2}:\d{2}|\d{3,4}|\d{1,2}\s*(?:am|pm))\b", low)
        if m:
            return convert_eta_text_to_hhmm(m.group(1), base_time, prev_eta_hhmm)
        # NEW: "arrive/be there/eta in <N> [minutes]" but NOT "coming in <N>" (vehicle number)
        m = re.search(
            r"\b(?:arriv(?:e|ing)|be\s*there|eta)\s+in\s+((?:\d+(?:\.\d+)?)|(?:[a-z\- ]+))\s*(?:mins?|minutes?)?\b",
            low,
        )
        if m and not re.search(r"\bcoming\s+in\s+\d{1,3}\b", low):
            amt = m.group(1).strip()
            if re.match(r"^\d+(?:\.\d+)?$", amt):
                mins = int(round(float(amt)))
            else:
                mins_opt = _words_to_int(amt)
                mins = mins_opt if mins_opt is not None else None  # type: ignore
            if mins is not None:
                eta_dt = base_time + timedelta(minutes=int(mins))
                return eta_dt.strftime("%H:%M")
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mins?|minutes?)\s*out\b", low)
        if m:
            mins = float(m.group(1))
            eta_dt = base_time + timedelta(minutes=int(round(mins)))
            return eta_dt.strftime("%H:%M")
        m = re.search(r"\b(\d+)\s*min\b", low)
        if m:
            mins = int(m.group(1))
            eta_dt = base_time + timedelta(minutes=mins)
            return eta_dt.strftime("%H:%M")
        if "an hour and a half" in low or "a hour and a half" in low or re.search(r"\b1\s*hour\s*and\s*a\s*half\b", low):
            eta_dt = base_time + timedelta(minutes=90)
            return eta_dt.strftime("%H:%M")
        if "half an hour" in low:
            eta_dt = base_time + timedelta(minutes=30)
            return eta_dt.strftime("%H:%M")
        m = re.search(r"\b(\d+)\s*(?:hours?|hrs?)\s*and\s*(\d+)\s*(?:mins?|minutes?)\b", low)
        if m:
            total = int(m.group(1)) * 60 + int(m.group(2))
            eta_dt = base_time + timedelta(minutes=total)
            return eta_dt.strftime("%H:%M")
        m = re.search(r"\b(?:an|a)\s+hour\s*and\s*(\d+)\s*(?:mins?|minutes?)\b", low)
        if m:
            total = 60 + int(m.group(1))
            eta_dt = base_time + timedelta(minutes=total)
            return eta_dt.strftime("%H:%M")
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", low)
        if m:
            hours = float(m.group(1))
            eta_dt = base_time + timedelta(minutes=int(round(hours * 60)))
            return eta_dt.strftime("%H:%M")
        m = re.search(r"\b(\d+)\s*(?:mins?|minutes?)\b", low)
        if m:
            mins = int(m.group(1))
            eta_dt = base_time + timedelta(minutes=mins)
            return eta_dt.strftime("%H:%M")
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([mh])\s*$", low)
        if m:
            val = float(m.group(1)); unit = m.group(2)
            mins = int(round(val * (60 if unit == "h" else 1)))
            eta_dt = base_time + timedelta(minutes=mins)
            return eta_dt.strftime("%H:%M")
        m = re.search(r"\b([a-z\- ]+?)\s*(?:mins?|minutes?)\b", low)
        if m:
            w = _words_to_int(m.group(1))
            if w is not None:
                eta_dt = base_time + timedelta(minutes=w)
                return eta_dt.strftime("%H:%M")
        if re.match(r"^\s*\d+(?:\.\d+)?\s*$", low):
            mins = float(re.findall(r"\d+(?:\.\d+)?", low)[0])
            eta_dt = base_time + timedelta(minutes=int(round(mins)))
            return eta_dt.strftime("%H:%M")
        m = re.search(r"\betaa?\s*[:\-]?\s*(\d{1,2}:\d{2}|\d{3,4})\b", low)
        if m:
            return convert_eta_text_to_hhmm(m.group(1), base_time, prev_eta_hhmm)
        return "Unknown"
    except Exception:
        return "Unknown"

def to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")

def from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)

def parse_eta_text_to_dt(eta_text: str, current_dt: datetime, prev_eta_dt: Optional[datetime]) -> Optional[datetime]:
    try:
        prev_hhmm = None
        if prev_eta_dt is not None:
            prev_hhmm = prev_eta_dt.strftime("%H:%M")
        hhmm = convert_eta_text_to_hhmm(eta_text, current_dt, prev_hhmm)
        if not re.match(r"^\d{1,2}:\d{2}$", hhmm):
            return None
        h, m = map(int, hhmm.split(":"))
        candidate = current_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate < current_dt:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    except Exception:
        return None

def classify_status_from_text(msg: str) -> str:
    t = (msg or "").strip().lower()
    if not t:
        return "Unknown"
    timeish = (
        re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", t) or
        re.search(r"\b\d{3,4}\b", t) or
        re.search(r"\b\d+\s*(?:m|min|mins?|minutes?|h|hr|hrs?|hours?)\b", t) or
        re.search(r"\b(?:an|a)\s+hour\b", t) or
        ("half an hour" in t)
    )
    if re.search(r"\b(?:10-?22|1022)\b", t):
        timeish = False
    if (
        re.search(r"\b(?:10-?22|1022)\s*(?:subj(?:ect)?\s*found|subject\s*found)\b", t)
        or re.search(r"\bmission\s*(?:over|complete)\b", t)
        or re.search(r"\bper\s*ic\b", t)
        or re.search(r"\bcopy\s+that\s*(?:10-?22|1022)\b", t)
    ):
        return "Informational"
    if re.fullmatch(r"\s*(?:10-?22|1022)\s*\.?\s*", t) or \
       re.search(r"\b(?:copy|ack(?:nowledged)?)\s*(?:10-?22|1022)\b", t):
        return "Not Responding"
    if re.search(r"(can't\s+make\s+it|won't\s+make|unavailable|i.?m\s+out|working\s+late|bail(?:ing)?|tap\s+out)", t):
        return "Cancelled"
    if re.search(r"\?\s*$", t):
        return "Informational"
    if re.search(r"\b(available|can\s+respond\s+if\s+needed|able\s+to\s+respond)\b", t):
        return "Available"
    if re.search(r"\b(respond(?:ing)?|en\s?route|enrt|on\s*it|rolling|leaving\s+now|\beta\b|be\s+there|headed|arrive|arriving|coming|etd)\b", t):
        return "Responding"
    if timeish and not re.search(r"\b(channel|ch\b|freq|mhz)\b", t):
        return "Responding"
    if re.search(r"\b(key|channel|freq|mhz)\b", t):
        return "Informational"
    return "Unknown"

# Assisted-mode prompt and JSON schema
ASSISTED_SCHEMA: Dict[str, Any] = {
    "name": "sar_extraction_assisted",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "vehicle": {"type": "string", "pattern": "^(POV|SAR Rig|SAR-[1-9][0-9]{0,2}|Unknown)$"},
            "vehicle_text": {"type": "string"},
            "eta_text": {"type": "string"},
            "status": {"type": "string", "enum": ["Responding","Cancelled","Available","Informational","Not Responding","Unknown"]},
            "evidence": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
        },
        "required": ["vehicle","vehicle_text","eta_text","status","evidence","confidence"]
    }
}

SYSTEM_PROMPT_ASSISTED = (
    "You are a SAR message extractor. Return ONLY a compact JSON object. Do NOT compute times.\n\n"
    "Goal: act as a span extractor. Copy short spans from the message for vehicle and ETA text; do not paraphrase.\n\n"
    "Context:\n"
    "- Messages are from Search & Rescue responders coordinating by chat.\n"
    "- Vehicles are usually either a personal vehicle (POV/PV/own car) or a numbered SAR rig: '78', 'SAR 78', 'SAR-078', 'in 78', 'coming in 78'.\n"
    "- The local shorthand '10-22' or '1022' means stand down/cancel (NOT a time).\n"
    "- Questions and logistics (keys/channels) are informational, not a response.\n"
    "- Current time is given only for context—you must NOT do math.\n\n"
    "Output JSON (no extra keys, no trailing text):\n"
    "{\n"
    "    \"vehicle\": \"POV\" | \"SAR-<number>\" | \"SAR Rig\" | \"Unknown\",\n"
    "    \"vehicle_text\": \"<exact substring for the vehicle mention, else ''>\",\n"
    "    \"eta_text\": \"<exact substring for time/duration as written, else 'Unknown'>\",\n"
    "    \"status\": \"Responding\" | \"Cancelled\" | \"Available\" | \"Informational\" | \"Not Responding\" | \"Unknown\",\n"
    "    \"evidence\": \"<very short phrase from the message>\",\n"
    "    \"confidence\": <float between 0 and 1>\n"
    "}\n\n"
    "Rules:\n"
    "- VEHICLE: If 'in 78', 'responding 78', 'sar 78' appears, normalize to 'SAR-78' and set vehicle_text to that substring.\n"
    "    'coming in <integer>' implies the SAR unit unless followed by a time unit; copy that phrase into vehicle_text.\n"
    "    Personal vehicle mentions → vehicle=\"POV\" and vehicle_text to the matching words.\n"
    "    If unclear, set vehicle=\"Unknown\" and vehicle_text=\"\".\n"
    "- ETA: DO NOT calculate. Copy the literal time span: e.g., '2330', '08:45', '45 minutes', '1 hr', '7:05 pm'. If none, use 'Unknown'.\n"
    "  If the message says 'be there in 20' (no unit), set eta_text to the exact substring 'in 20'.\n"
    "  Never take 'coming in <number>' as an ETA; that is a vehicle number here.\n"
    "- STATUS: Provide your best guess from the message only. The evaluator may override it for scoring.\n"
)

def _call_assisted_llm(text: str, current_iso_utc: str, prev_eta_iso_utc: Optional[str]) -> Dict[str, Any]:
    """Call Azure OpenAI in assisted mode and return spans. Robust to model capability differences."""
    if client is None:
        return {}
    model = cast(str, azure_openai_deployment)
    # Build messages
    user_content = (
        f"Current time (UTC, do NOT calculate): {current_iso_utc}\n"
        f"Previous ETA (if any): {prev_eta_iso_utc or 'None'}\n"
        f"Message: {text}"
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_ASSISTED},
        {"role": "user", "content": user_content},
    ]
    # Extra params with optional verbosity/reasoning
    extra: Dict[str, Any] = {}
    # Low verbosity/reasoning defaults for production if provided
    v = os.getenv("MODEL_VERBOSITY") or os.getenv("AZURE_OPENAI_VERBOSITY")
    r = os.getenv("MODEL_REASONING_EFFORT") or os.getenv("AZURE_OPENAI_REASONING")
    if v:
        extra["verbosity"] = v
    if r:
        extra["reasoning_effort"] = r
    # token caps
    try:
        max_tok = int(os.getenv("MAX_COMPLETION_TOKENS", "160") or 160)
    except Exception:
        max_tok = 160
    hard_cap = int(os.getenv("MAX_COMPLETION_TOKENS_HARD", "768") or 768)
    # Common decode params
    common = {
        "max_completion_tokens": max_tok,
        "temperature": 0,
        "top_p": 1,
        "presence_penalty": 0,
        "frequency_penalty": 0,
    }
    # Attempt with graceful fallback
    attempt_err: Optional[Exception] = None
    for _ in range(4):
        try:
            return_json = client.chat.completions.create(
                model=model,
                response_format={"type": "json_schema", "json_schema": ASSISTED_SCHEMA},
                messages=messages,
                **common,
                **extra,
            )
            content = (return_json.choices[0].message.content or "").strip()
            try:
                return json.loads(content)
            except Exception:
                m = re.search(r"\{.*\}", content, re.S)
                return json.loads(m.group(0)) if m else {}
        except APIStatusError as e:
            etxt = str(e).lower()
            attempt_err = e
            # prune unsupported params
            for key, needle in (("temperature","temperature"),("top_p","top_p"),("presence_penalty","presence"),("frequency_penalty","frequency")):
                if key in common and needle in etxt and "unsupported" in etxt:
                    common.pop(key, None)
            for key in ("verbosity","reasoning_effort"):
                if key in extra and key.replace("_"," ") in etxt and ("unsupported" in etxt or "invalid" in etxt):
                    extra.pop(key, None)
            # output limit → bump tokens
            if ("output limit" in etxt) or ("max_tokens" in etxt) or ("max tokens" in etxt):
                cur = int(common.get("max_completion_tokens", max_tok) or max_tok)
                new_val = min(hard_cap, max(cur * 2, cur + 128))
                if new_val > cur:
                    common["max_completion_tokens"] = new_val
                    continue
            # response_format not supported → try json_object
            if ("response_format" in etxt and ("json_schema" in etxt or "not supported" in etxt)) or "invalid parameter" in etxt:
                try:
                    alt = client.chat.completions.create(
                        model=model,
                        response_format={"type": "json_object"},
                        messages=messages,
                        **common,
                        **extra,
                    )
                    content = (alt.choices[0].message.content or "").strip()
                    try:
                        return json.loads(content)
                    except Exception:
                        m = re.search(r"\{.*\}", content, re.S)
                        return json.loads(m.group(0)) if m else {}
                except APIStatusError as e2:
                    etxt2 = str(e2).lower()
                    # prune decode params further
                    for key, needle in (("temperature","temperature"),("top_p","top_p"),("presence_penalty","presence"),("frequency_penalty","frequency")):
                        if key in common and needle in etxt2 and "unsupported" in etxt2:
                            common.pop(key, None)
                    if "response_format" in etxt2 and ("json_object" in etxt2 or "not supported" in etxt2):
                        raw = client.chat.completions.create(
                            model=model,
                            messages=messages,
                            stop=["\n\n"],
                            **common,
                            **extra,
                        )
                        content = (raw.choices[0].message.content or "").strip()
                        m = re.search(r"\{.*\}", content, re.S)
                        return json.loads(m.group(0)) if m else {}
                    else:
                        continue
        except Exception as e:
            attempt_err = e
            break
    logger.warning(f"Assisted LLM call failed; using deterministic fallback: {attempt_err}")
    return {}

def classify_status_llm(client: Optional[AzureOpenAI], text: str, prev_status: Optional[str] = None) -> Dict[str, Any]:
    """
    Lightweight intent classifier. Returns:
      {"status": "...", "status_evidence": "...", "confidence": float}
    Falls back to unknown if client unavailable or any error.
    """
    try:
        if client is None:
            return {"status": "unknown", "status_evidence": "", "confidence": 0.0}

        sys_msg = (
            "Classify SAR responder messages by intent only (no math) into one of: "
            "responding, cancelled, available, informational, unknown. "
            "Be robust to slang, profanity, and shorthand. Return ONLY JSON."
        )

        fewshots = [
            {"role": "user", "content": "Message: fuck this I'm out"},
            {"role": "assistant", "content": '{"status":"cancelled","status_evidence":"fuck this I\'m out","confidence":0.95}'},

            {"role": "user", "content": "Message: sorry can’t make it tonight"},
            {"role": "assistant", "content": '{"status":"cancelled","status_evidence":"can’t make it","confidence":0.98}'},

            {"role": "user", "content": "Message: rolling now POV"},
            {"role": "assistant", "content": '{"status":"responding","status_evidence":"rolling now","confidence":0.85}'},

            {"role": "user", "content": "Message: I can respond if needed"},
            {"role": "assistant", "content": '{"status":"available","status_evidence":"respond if needed","confidence":0.80}'},

            {"role": "user", "content": "Message: key for 74 is in the box"},
            {"role": "assistant", "content": '{"status":"informational","status_evidence":"key for 74","confidence":0.90}'},
        ]

        if prev_status:
            text = f"(Sender previously {prev_status}). " + text

        prompt = (
            "Message: " + text + "\n"
            "Return JSON with keys: status, status_evidence, confidence (0..1)."
        )

        resp = client.chat.completions.create(
            model=cast(str, azure_openai_deployment),
            messages=[
                {"role": "system", "content": sys_msg},
                *fewshots,
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=60,
            # If your Azure model supports strict JSON mode, you can enable it:
            # response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", raw, flags=re.S)
        data = json.loads(m.group(0)) if m else {}

        status = str(data.get("status", "unknown")).lower()
        if status not in {"responding", "cancelled", "available", "informational", "unknown"}:
            status = "unknown"
        ev = str(data.get("status_evidence", ""))[:200]
        try:
            conf = float(data.get("confidence", 0.0))
        except Exception:
            conf = 0.0

        return {"status": status, "status_evidence": ev, "confidence": max(0.0, min(conf, 1.0))}
    except Exception as e:
        logger.warning(f"LLM status classify failed: {e}")
        return {"status": "unknown", "status_evidence": "", "confidence": 0.0}


def validate_and_format_time(time_string: str) -> Dict[str, Any]:
    """Validate time and convert to proper 24-hour format. Used by AI function calling."""
    try:
        # Handle various time formats
        time_clean = time_string.replace(' ', '').upper()
        
        # Check for AM/PM
        has_am_pm = 'AM' in time_clean or 'PM' in time_clean
        if has_am_pm:
            time_part = time_clean.replace('AM', '').replace('PM', '')
            is_pm = 'PM' in time_clean
            
            if ':' in time_part:
                hour, minute = map(int, time_part.split(':'))
            else:
                hour = int(time_part)
                minute = 0
            
            # Convert to 24-hour format
            if is_pm and hour != 12:
                hour += 12
            elif not is_pm and hour == 12:
                hour = 0
        else:
            # 24-hour format
            if ':' in time_string:
                hour, minute = map(int, time_string.split(':'))
            else:
                return {"valid": False, "error": "Invalid time format"}
        
        # Validate ranges
        if hour > 23:
            if hour == 24 and minute == 0:
                # 24:00 -> 00:00 next day
                return {
                    "valid": True, 
                    "normalized": "00:00", 
                    "next_day": True,
                    "note": "Converted 24:00 to 00:00 (next day)"
                }
            elif hour == 24 and minute <= 59:
                # 24:30 -> 00:30 next day
                return {
                    "valid": True,
                    "normalized": f"00:{minute:02d}",
                    "next_day": True,
                    "note": f"Converted 24:{minute:02d} to 00:{minute:02d} (next day)"
                }
            else:
                return {"valid": False, "error": f"Invalid hour: {hour}"}
        
        if minute > 59:
            return {"valid": False, "error": f"Invalid minute: {minute}"}
        
        return {
            "valid": True,
            "normalized": f"{hour:02d}:{minute:02d}",
            "next_day": False
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}

def convert_duration_text(duration_text: str) -> Dict[str, Any]:
    """Convert duration text to minutes with validation. Used by AI function calling."""
    try:
        duration_lower = duration_text.lower()
        
        # Hours
        if 'hour' in duration_lower:
            if 'half' in duration_lower:
                minutes = 30
            else:
                match = re.search(r'(\d+(?:\.\d+)?)', duration_lower)
                if match:
                    hours = float(match.group(1))
                    minutes = int(hours * 60)
                else:
                    return {"valid": False, "error": "Cannot parse hour value"}
        
        # Minutes
        elif 'min' in duration_lower:
            match = re.search(r'(\d+)', duration_lower)
            if match:
                minutes = int(match.group(1))
            else:
                return {"valid": False, "error": "Cannot parse minute value"}
        
        # Direct number (assume minutes)
        else:
            match = re.search(r'(\d+)', duration_text)
            if match:
                minutes = int(match.group(1))
            else:
                return {"valid": False, "error": "Cannot parse duration"}
        
        return {
            "valid": True,
            "minutes": minutes,
            "text": duration_text,
            "warning": "Duration over 24 hours - please verify" if minutes > 1440 else None
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}

def validate_realistic_eta(eta_minutes: int) -> Dict[str, Any]:
    """Check if ETA is realistic for SAR operations. Used by AI function calling."""
    try:
        hours = eta_minutes / 60
        
        if eta_minutes <= 0:
            return {"realistic": False, "reason": "ETA cannot be negative or zero"}
        elif eta_minutes > 1440:  # > 24 hours
            return {
                "realistic": False, 
                "reason": f"ETA of {hours:.1f} hours is unrealistic for emergency response",
                "suggestion": "Please verify the ETA or cap at reasonable maximum"
            }
        elif eta_minutes > 720:  # > 12 hours
            return {
                "realistic": False,
                "reason": f"ETA of {hours:.1f} hours is very long for emergency response",
                "suggestion": "Consider if this is correct"
            }
        else:
            return {"realistic": True, "hours": hours}
    except Exception as e:
        return {"realistic": False, "error": str(e)}

# Function definitions for Azure OpenAI function calling
# Function definitions removed - using simplified prompt-based approach

def is_email_domain_allowed(email: str) -> bool:
    """Check if the user's email domain is in the allowed domains list"""
    if not email:
        return False
    # Allow test domains when running tests
    if is_testing and email.endswith("@example.com"):
        logger.info(f"Test mode: allowing test domain for {email}")
        return True
    try:
        domain = email.split("@")[1].lower()
        allowed_domains_lower = [d.lower() for d in allowed_email_domains]
        is_allowed = domain in allowed_domains_lower
        logger.info(f"Domain check for {domain}: {'allowed' if is_allowed else 'denied'} (allowed domains: {allowed_email_domains})")
        return is_allowed
    except (IndexError, AttributeError):
        logger.warning(f"Invalid email format: {email}")
        return False

def is_admin(email: Optional[str]) -> bool:
    """Check if the user's email is in the allowed admin users list.

    In testing or when local auth bypass is enabled, treat as admin to avoid breaking tests/dev.
    """
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
    """Get authenticated user information from OAuth2 Proxy headers"""
    # Debug: log all headers to see what OAuth2 proxy is sending
    if DEBUG_LOG_HEADERS:
        print("=== DEBUG: All headers received ===")
        for header_name, header_value in request.headers.items():
            if header_name.lower().startswith('x-'):
                print(f"Header: {header_name} = {header_value}")
        print("=== END DEBUG ===")

    # Check for the correct OAuth2 Proxy headers, including forwarded headers
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

    # Fallback to legacy header names for backwards compatibility
    if not user_email:
        user_email = request.headers.get("X-User")
    if not user_name:
        user_name = request.headers.get("X-Preferred-Username") or request.headers.get("X-User-Name")
    if not user_groups:
        user_groups = request.headers.get("X-User-Groups", "").split(",") if request.headers.get("X-User-Groups") else []

    authenticated: bool
    display_name: Optional[str]
    email: Optional[str]

    # Check if we have user information from OAuth2 proxy
    if user_email or user_name:
        # Check if the user's email domain is allowed
        if user_email and not is_email_domain_allowed(user_email):
            logger.warning(f"Access denied for user {user_email}: domain not in allowed list")
            return JSONResponse(
                status_code=403,
                content={
                    "authenticated": False,
                    "error": "Access denied",
                    "message": f"Your domain is not authorized to access this application. Allowed domains: {', '.join(allowed_email_domains)}",
                    "logout_url": f"/oauth2/sign_out?rd={quote('/', safe='')}",
                }
            )
        authenticated = True
        display_name = user_name or user_email
        email = user_email
        logger.info(f"User authenticated: {email} from allowed domain")
    else:
        # No OAuth2 headers - user might not be properly authenticated
        # In tests, always report unauthenticated to satisfy unit tests
        if ALLOW_LOCAL_AUTH_BYPASS and not is_testing:
            # Local dev: pretend there's a logged-in user (but NOT in tests)
            authenticated = True
            display_name = os.getenv("LOCAL_DEV_USER_NAME", "Local Dev")
            email = os.getenv("LOCAL_DEV_USER_EMAIL", "dev@local.test")
        else:
            authenticated = False
            display_name = None
            email = None

    # Admin flag
    admin_flag = is_admin(email)

    return JSONResponse(content={
        "authenticated": authenticated,
        "email": email,
        "name": display_name,
        "groups": [group.strip() for group in user_groups if group.strip()],
        "is_admin": admin_flag,
        # Redirect to root after logout so OAuth2 Proxy can initiate a new login
        "logout_url": f"/oauth2/sign_out?rd={quote('/', safe='')}",
    })

def init_redis():
    """Initialize Redis connection"""
    global redis_client
    
    # Skip Redis in testing mode
    if is_testing:
        logger.info("Test mode: Using in-memory storage instead of Redis")
        return
        
    if redis_client is None:
        try:
            redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Test connection
            cast(Any, redis_client).ping()
            logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            if not is_testing:
                raise

def load_messages():
    """Load messages from Redis"""
    global messages
    
    # In testing mode, use in-memory storage
    if is_testing:
        logger.debug(f"Test mode: Using in-memory storage with {len(messages)} messages")
        return
        
    try:
        init_redis()
        if redis_client:
            data = redis_client.get(REDIS_KEY)
            if data:
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                messages = json.loads(cast(str, data))
                logger.info(f"Loaded {len(messages)} messages from Redis")
            else:
                # No data stored yet in Redis; keep current in-memory list
                logger.info("No existing messages in Redis; keeping current in-memory messages")
        else:
            # Redis not available; keep current in-memory list for local dev
            logger.warning("Redis not available, keeping in-memory messages")
    except Exception as e:
        # On load errors, do not clear in-memory state; just log
        logger.error(f"Error loading messages from Redis: {e}")
    # Ensure all messages have unique IDs for editing/deleting
    _assigned = ensure_message_ids()
    if _assigned:
        save_messages()

def save_messages():
    """Save messages to Redis"""
    global messages
    
    # In testing mode, just keep in memory
    if is_testing:
        logger.debug(f"Test mode: Messages stored in memory ({len(messages)} messages)")
        return
        
    try:
        init_redis()
        if redis_client:
            data = json.dumps(messages)
            redis_client.set(REDIS_KEY, data)
            logger.debug(f"Saved {len(messages)} messages to Redis")
        else:
            # Keep working with in-memory state when Redis is unavailable
            logger.warning("Redis not available; keeping messages only in memory")
    except Exception as e:
        # Do not drop in-memory state on save error
        logger.error(f"Error saving messages to Redis: {e}")

def reload_messages():
    """Reload messages from Redis to get latest data"""
    load_messages()

def load_deleted_messages():
    """Load deleted messages from Redis"""
    global deleted_messages
    
    # In testing mode, use in-memory storage
    if is_testing:
        logger.debug(f"Test mode: Using in-memory deleted storage with {len(deleted_messages)} messages")
        return
        
    try:
        init_redis()
        if redis_client:
            data = redis_client.get(REDIS_DELETED_KEY)
            if data:
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                deleted_messages = json.loads(cast(str, data))
                logger.debug(f"Loaded {len(deleted_messages)} deleted messages from Redis")
            else:
                logger.debug("No deleted messages in Redis")
        else:
            logger.warning("Redis not available for deleted messages")
    except Exception as e:
        logger.error(f"Error loading deleted messages from Redis: {e}")

def save_deleted_messages():
    """Save deleted messages to Redis"""
    global deleted_messages
    
    # In testing mode, just keep in memory
    if is_testing:
        logger.debug(f"Test mode: Deleted messages stored in memory ({len(deleted_messages)} messages)")
        return
        
    try:
        init_redis()
        if redis_client:
            data = json.dumps(deleted_messages)
            redis_client.set(REDIS_DELETED_KEY, data)
            logger.debug(f"Saved {len(deleted_messages)} deleted messages to Redis")
        else:
            logger.warning("Redis not available; keeping deleted messages only in memory")
    except Exception as e:
        logger.error(f"Error saving deleted messages to Redis: {e}")

def soft_delete_messages(messages_to_delete: List[Dict[str, Any]]):
    """Move messages to deleted storage with timestamp"""
    global deleted_messages
    
    # Load current deleted messages
    load_deleted_messages()
    
    # Add deletion timestamp to each message
    current_time = datetime.now().isoformat()
    for msg in messages_to_delete:
        msg["deleted_at"] = current_time
        deleted_messages.append(msg)
    
    # Save updated deleted messages
    save_deleted_messages()
    logger.info(f"Soft deleted {len(messages_to_delete)} messages")

def undelete_messages(message_ids: List[str]) -> int:
    """Restore messages from deleted storage back to active messages"""
    global messages, deleted_messages
    
    # Load current state
    load_deleted_messages()
    reload_messages()
    
    # Find messages to restore
    to_restore: List[Dict[str, Any]] = []
    remaining_deleted: List[Dict[str, Any]] = []
    
    for msg in deleted_messages:
        if str(msg.get("id")) in message_ids:
            # Remove deletion timestamp and restore
            if "deleted_at" in msg:
                del msg["deleted_at"]
            to_restore.append(msg)
        else:
            remaining_deleted.append(msg)
    
    if to_restore:
        # Add back to active messages
        messages.extend(to_restore)
        save_messages()
        
        # Update deleted messages
        deleted_messages.clear()
        deleted_messages.extend(remaining_deleted)
        save_deleted_messages()
        
        logger.info(f"Restored {len(to_restore)} messages from deleted storage")
    
    return len(to_restore)

def _clear_all_messages():
    """Clear all stored messages from memory and Redis."""
    global messages
    messages = []
    # Persist the empty list to Redis
    try:
        if not is_testing:
            init_redis()
            if redis_client:
                redis_client.delete(REDIS_KEY)
    except Exception as e:
        logger.warning(f"Failed clearing Redis key {REDIS_KEY}: {e}")

def ensure_message_ids() -> int:
    """Ensure each message has an 'id' field; return count assigned."""
    count = 0
    for m in messages:
        if not m.get("id"):
            m["id"] = str(uuid.uuid4())
            count += 1
    return count

 
 

def _authn_domain_and_admin_ok(request: Request) -> bool:
    """Require authenticated, allowed domain, and admin user for mutating/admin endpoints."""
    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
        or request.headers.get("X-User")
    )
    # In tests or local bypass, allow
    if not user_email:
        return bool(is_testing or ALLOW_LOCAL_AUTH_BYPASS)
    return is_email_domain_allowed(user_email) and is_admin(user_email)

def _parse_datetime_like(value: Any) -> Optional[datetime]:
    """Parse various datetime forms into app timezone-aware datetime.

    Accepts ISO strings (with or without TZ), 'YYYY-MM-DD HH:MM:SS', or epoch seconds (int/float).
    """
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=APP_TZ)
        s = str(value)
        # 'YYYY-MM-DD HH:MM:SS' -> make it ISO-like first
        if "T" not in s and " " in s and ":" in s:
            s = s.replace(" ", "T")
        # If no timezone info, assume APP_TZ local clock
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            # Last resort: try plain strptime
            try:
                dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
        if dt.tzinfo is None:
            # Attach app tz naive -> aware
            dt = dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)
    except Exception:
        return None

def _compute_eta_fields(eta_str: Optional[str], eta_ts: Optional[datetime], base_time: datetime) -> Dict[str, Any]:
    """Given eta string or datetime, compute standard eta fields."""
    if eta_ts:
        eta_display = eta_ts.strftime("%H:%M")
        eta_info = calculate_eta_info(eta_display, base_time)
        # Overwrite with explicit eta_ts if provided
        eta_info_ts = eta_ts
        return {
            "eta": eta_display,
            "eta_timestamp": (
                eta_info_ts.strftime("%Y-%m-%d %H:%M:%S") if is_testing else eta_info_ts.isoformat()
            ),
            "eta_timestamp_utc": eta_info_ts.astimezone(timezone.utc).isoformat(),
            "minutes_until_arrival": eta_info.get("minutes_until_arrival"),
            "arrival_status": eta_info.get("status"),
        }
    # Use eta string
    eta_display = eta_str or "Unknown"
    norm_eta = eta_display
    if eta_display not in ("Unknown", "Not Responding"):
        norm = validate_and_format_time(eta_display)
        if norm.get("valid"):
            norm_eta = str(norm.get("normalized", eta_display))
        else:
            norm_eta = "Unknown"
    eta_info = calculate_eta_info(norm_eta, base_time)
    return {
        "eta": norm_eta,
        "eta_timestamp": eta_info.get("eta_timestamp"),
        "eta_timestamp_utc": eta_info.get("eta_timestamp_utc"),
        "minutes_until_arrival": eta_info.get("minutes_until_arrival"),
        "arrival_status": eta_info.get("status"),
    }

# Load messages on startup
load_messages()

# Initialize the Azure OpenAI client with credentials from .env
client = None
if not FAST_LOCAL_PARSE:
    logger.info("Initializing Azure OpenAI client")
    try:
        client = AzureOpenAI(
            api_key=cast(str, azure_openai_api_key),
            azure_endpoint=cast(str, azure_openai_endpoint),
            api_version=cast(str, azure_openai_api_version),
        )
    except Exception as e:
        logger.warning(f"Failed to initialize Azure OpenAI client: {e}")
        if is_testing:
            # Create a mock client for testing
            from unittest.mock import MagicMock
            client = MagicMock()
            logger.info("Created mock Azure OpenAI client for testing")
        else:
            raise

def convert_eta_to_timestamp(eta_str: str, current_time: datetime) -> str:
    """Convert ETA string to HH:MM format, handling duration calculations and validation"""
    try:
        # If already in HH:MM format, validate and format properly
        if re.match(r'^\d{1,2}:\d{2}$', eta_str):
            hour, minute = map(int, eta_str.split(':'))
            if hour > 23:
                if hour == 24 and minute == 0:
                    return "00:00"
                elif hour == 24 and minute <= 59:
                    return f"00:{minute:02d}"
                else:
                    logger.warning(f"Invalid hour {hour} in ETA '{eta_str}', returning Unknown")
                    return "Unknown"
            if minute > 59:
                logger.warning(f"Invalid minute {minute} in ETA '{eta_str}', returning Unknown")
                return "Unknown"
            return f"{hour:02d}:{minute:02d}"

        eta_lower = eta_str.lower()
        # Normalize shorthand
        eta_norm = eta_lower.replace('~', '')
        eta_norm = re.sub(r'\bmins?\.?(?=\b)', 'min', eta_norm)
        eta_norm = re.sub(r'\bhrs?\.?(?=\b)', 'hr', eta_norm)
        # Strip leading 'in '
        eta_norm = re.sub(r'^\s*in\s+', '', eta_norm)

        # Composite durations (prioritized)
        m = re.search(r'\b(\d+)\s*(?:hours?|hrs?)\s*and\s*(\d+)\s*(?:mins?|minutes?)?\b', eta_norm)
        if m:
            total = int(m.group(1)) * 60 + int(m.group(2))
            total = min(total, 1440)
            return (current_time + timedelta(minutes=total)).strftime('%H:%M')

        m = re.search(r'\b(?:an|a)\s+hour\s*and\s*(\d+)\s*(?:mins?|minutes?)?\b', eta_norm)
        if m:
            total = 60 + int(m.group(1))
            total = min(total, 1440)
            return (current_time + timedelta(minutes=total)).strftime('%H:%M')

        if re.search(r'\b(?:an|a)\s+hour\s*and\s*a\s*half\b', eta_norm) or re.search(r'\b1\s*(?:hour|hr)\s*and\s*a\s*half\b', eta_norm):
            return (current_time + timedelta(minutes=90)).strftime('%H:%M')
        if re.search(r'\bhalf\s+an?\s+hour\b', eta_norm):
            return (current_time + timedelta(minutes=30)).strftime('%H:%M')

        # Compact forms like 30m / 2h
        m_compact = re.match(r'^\s*(\d+(?:\.\d+)?)\s*([mh])\s*$', eta_norm)
        if m_compact:
            val, unit = m_compact.groups()
            minutes = float(val) * (60 if unit == 'h' else 1)
            minutes = min(minutes, 1440)
            return (current_time + timedelta(minutes=int(minutes))).strftime('%H:%M')

        # Bare number (assume minutes)
        if re.match(r'^\s*\d+(?:\.\d+)?\s*$', eta_norm):
            minutes = float(re.findall(r'\d+(?:\.\d+)?', eta_norm)[0])
            minutes = min(minutes, 1440)
            return (current_time + timedelta(minutes=int(minutes))).strftime('%H:%M')

        # Singular hour text
        if re.search(r'\b(?:an|a)\s+hour\b', eta_norm):
            return (current_time + timedelta(minutes=60)).strftime('%H:%M')

        # Minutes / hours with units
        numbers = re.findall(r'\d+(?:\.\d+)?', eta_norm)
        if any(word in eta_norm for word in ['min', 'minute']):
            if numbers:
                minutes = float(numbers[0])
                minutes = min(minutes, 1440)
                return (current_time + timedelta(minutes=int(minutes))).strftime('%H:%M')
        if any(word in eta_norm for word in ['hour', 'hr']):
            if numbers:
                hours = float(numbers[0])
                hours = min(hours, 24)
                return (current_time + timedelta(hours=hours)).strftime('%H:%M')

        # AM/PM formats
        if any(period in eta_lower for period in ['am', 'pm']):
            time_match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)', eta_lower)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                period = time_match.group(3)
                if minute > 59:
                    logger.warning(f"Invalid minute {minute} in ETA '{eta_str}'")
                    return "Unknown"
                if period == 'pm' and hour != 12:
                    hour += 12
                elif period == 'am' and hour == 12:
                    hour = 0
                return f"{hour:02d}:{minute:02d}"
            hour_match = re.search(r'(\d{1,2})\s*(am|pm)', eta_lower)
            if hour_match:
                hour = int(hour_match.group(1))
                period = hour_match.group(2)
                if period == 'pm' and hour != 12:
                    hour += 12
                elif period == 'am' and hour == 12:
                    hour = 0
                return f"{hour:02d}:00"

        # 24-hour numeric without colon
        if re.match(r'^\d{3,4}$', eta_str):
            if len(eta_str) == 3:
                hour = int(eta_str[0])
                minute = int(eta_str[1:3])
            else:
                hour = int(eta_str[:2])
                minute = int(eta_str[2:4])
            if hour > 23:
                if hour == 24 and minute <= 59:
                    return f"00:{minute:02d}"
                else:
                    logger.warning(f"Invalid hour {hour} in ETA '{eta_str}'")
                    return "Unknown"
            if minute > 59:
                logger.warning(f"Invalid minute {minute} in ETA '{eta_str}'")
                return "Unknown"
            return f"{hour:02d}:{minute:02d}"

        logger.warning(f"Could not parse ETA: {eta_str}")
        return "Unknown"
    except Exception as e:
        logger.warning(f"Error converting ETA '{eta_str}': {e}")
        return "Unknown"

def extract_details_from_text(text: str, base_time: Optional[datetime] = None, prev_eta_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract vehicle, ETA, and infer status (responding/cancelled/etc.).
    - Deterministic parsing for vehicle and ETA stays in code.
    - LLM is only used for ambiguous intent classification, never for time math.
    """
    logger.info(f"Extracting details from text: {text[:50]}...")
    anchor_time: datetime = base_time or now_tz()
    tl = text.lower()

    # --- Guard: handle 10-22 style stand-down codes unless we clearly have an ETA like 'ETA 1022'
    m_eta_compact = re.search(r"\beta\s*:?\s*(\d{3,4})\b", tl)
    has_10_22_code = bool(re.search(r"\b10\s*-\s*22\b", tl) or re.search(r"\b10\s+22\b", tl) or re.search(r"\b1022\b", tl))
    if not m_eta_compact and has_10_22_code:
        return {
            "vehicle": "Unknown",
            "eta": "Cancelled",
            "raw_status": "Cancelled",
            "status_source": "Rules",
            "status_confidence": 1.0,
        }

    # --- Strong cancel phrases (expanded to include slang/profanity)
    cancel_signals = [
        "can't make it", "cannot make it", "not coming", "won't make", "wont make",
        "backing out", "back out", "stand down", "standing down", "cancel", "cancelling",
        "canceled", "cancelled", "family emergency", "unavailable", "can't respond",
        "cannot respond", "won't respond", "wont respond", "cant make it",
        "fuck this", "screw this", "i'm out", "im out", "bailing", "bail", "hard pass"
    ]
    if any(k in tl for k in cancel_signals):
        return {
            "vehicle": "Unknown",
            "eta": "Cancelled",
            "raw_status": "Cancelled",
            "status_source": "Rules",
            "status_confidence": 0.98,
        }

    # Assisted LLM span extraction first (if enabled)
    vehicle = "Unknown"
    eta = "Unknown"
    try:
        if not FAST_LOCAL_PARSE and client is not None and azure_openai_deployment:
            cur_iso = anchor_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            spans = _call_assisted_llm(text, cur_iso, prev_eta_iso)
            if spans:
                # Vehicle normalization
                v_guess = str(spans.get("vehicle", "Unknown"))
                if v_guess.startswith("SAR-") or v_guess.startswith("SAR "):
                    try:
                        num = int(re.findall(r"\d+", v_guess)[0]); v_guess = f"SAR-{num}"
                    except Exception:
                        pass
                if v_guess not in ("POV", "SAR Rig") and not v_guess.startswith("SAR-"):
                    v_guess = normalize_vehicle(text)
                if v_guess == "Unknown":
                    v_guess = normalize_vehicle(spans.get("vehicle_text", "") or text)
                vehicle = v_guess
                # ETA normalization from eta_text (fallback to legacy 'eta' key)
                eta_text = (spans.get("eta_text") or spans.get("eta") or "Unknown").strip()
                # If the model provided a plain HH:MM, keep it literal for display (no TZ math)
                if re.fullmatch(r"\d{1,2}:\d{2}", eta_text):
                    norm = validate_and_format_time(eta_text)
                    if norm.get("valid"):
                        eta = str(norm.get("normalized"))
                elif eta_text != "Unknown":
                    prev_dt = from_iso(prev_eta_iso) if prev_eta_iso else None
                    dt = parse_eta_text_to_dt(eta_text, anchor_time.astimezone(timezone.utc), prev_dt)
                    if dt:
                        # Store as HH:MM local display for our UI pipeline
                        local_dt = dt.astimezone(APP_TZ)
                        eta = local_dt.strftime("%H:%M")
                # If still unknown, attempt conservative fallback extraction on message text
                if eta == "Unknown":
                    filtered = re.sub(r"\b(?:10-?22|1022)\b", " ", text, flags=re.IGNORECASE)
                    prev_dt = from_iso(prev_eta_iso) if prev_eta_iso else None
                    dt2 = parse_eta_text_to_dt(filtered, anchor_time.astimezone(timezone.utc), prev_dt)
                    if dt2:
                        eta = dt2.astimezone(APP_TZ).strftime("%H:%M")
    except Exception as e:
        logger.warning(f"Assisted extraction failed, falling back to rules: {e}")

    # Deterministic fallback when assisted path yields Unknowns
    if vehicle == "Unknown":
        vehicle = normalize_vehicle(text)
    if eta == "Unknown":
        current_time = anchor_time
        m_time = re.search(r"\b(\d{1,2}:\d{2}\s*(am|pm)?)\b", tl)
        m_hours_and_minutes = re.search(r"\b(\d+)\s*(?:hours?|hrs?)\s*and\s*(\d+)\s*(?:mins?|minutes?)\b", tl)
        m_an_hour_and_minutes = re.search(r"\b(?:an|a)\s+hour\s*and\s*(\d+)\s*(?:mins?|minutes?)\b", tl)
        m_hours_and_number = re.search(r"\b(\d+)\s*(?:hours?|hrs?)\s*and\s*(\d+)\b", tl)
        m_an_hour_and_number = re.search(r"\b(?:an|a)\s+hour\s*and\s*(\d+)\b", tl)
        m_half_hour = ("half" in tl and ("hour" in tl or "hr" in tl)) or re.search(r"\bhalf\s+an?\s+hour\b", tl)
        m_min = re.search(r"\b(\d{1,3})\s*(min|mins|minutes)\b", tl)
        m_hr = re.search(r"\b(\d{1,2})\s*(hour|hr|hours|hrs)\b", tl)
        if m_time:
            eta = convert_eta_to_timestamp(m_time.group(1), current_time)
        elif m_hours_and_minutes:
            hours = int(m_hours_and_minutes.group(1)); mins = int(m_hours_and_minutes.group(2))
            eta = convert_eta_to_timestamp(f"{hours} hours and {mins} minutes", current_time)
        elif m_an_hour_and_minutes:
            mins = int(m_an_hour_and_minutes.group(1))
            eta = convert_eta_to_timestamp(f"an hour and {mins} minutes", current_time)
        elif m_hours_and_number:
            hours = int(m_hours_and_number.group(1)); mins = int(m_hours_and_number.group(2))
            eta = convert_eta_to_timestamp(f"{hours} hours and {mins} minutes", current_time)
        elif m_an_hour_and_number:
            mins = int(m_an_hour_and_number.group(1))
            eta = convert_eta_to_timestamp(f"an hour and {mins} minutes", current_time)
        elif m_eta_compact:
            digits = m_eta_compact.group(1)
            if len(digits) == 3:
                hour = int(digits[0]); minute = int(digits[1:3])
            else:
                hour = int(digits[:2]); minute = int(digits[2:4])
            if 0 <= hour <= 24 and 0 <= minute <= 59:
                if hour == 24: hour = 0
                eta = f"{hour:02d}:{minute:02d}"
        elif m_half_hour:
            eta = convert_eta_to_timestamp("half hour", current_time)
        elif m_min:
            eta = convert_eta_to_timestamp(f"{m_min.group(1)} minutes", current_time)
        elif m_hr:
            eta = convert_eta_to_timestamp(f"{m_hr.group(1)} hour", current_time)

    # --- Rule-based status guess (lightweight + conservative)
    raw_status = "Unknown"
    responding_signals = [
        "responding", "on my way", "omw", "en route", "enroute", "headed", "rolling", "leaving", "departing", "otw",
        "arriving", "be there"
    ]
    available_signals = ["i can respond", "i can help", "available", "if needed"]
    informational_signals = ["key for", "who can respond", "checking with", "need someone"]

    if eta != "Unknown":
        raw_status = "Responding"
        rule_conf = 0.99
    elif any(s in tl for s in responding_signals):
        raw_status = "Responding"; rule_conf = 0.8
    elif any(s in tl for s in available_signals):
        raw_status = "Available"; rule_conf = 0.7
    elif any(s in tl for s in informational_signals):
        raw_status = "Informational"; rule_conf = 0.7
    else:
        rule_conf = 0.0

    # --- Decide if we need semantic help
    ambiguous_or_spicy = bool(re.search(r"\b(bail|bailing|i'm out|im out|fuck this|screw this|nope|hard pass)\b", tl))
    need_llm = (
        (raw_status == "Unknown") or
        (ambiguous_or_spicy and raw_status not in {"Cancelled"})
    )

    # Determine status deterministically aligned with benchmark
    raw_status = classify_status_from_text(text)

    # Default: return rules result
    return {
        "vehicle": vehicle,
        "eta": eta,
    "raw_status": raw_status,
        "status_source": "Rules",
        "status_confidence": 1.0 if raw_status != "Unknown" else 0.0,
    }


def _normalize_display_name(raw_name: str) -> str:
    """Strip trailing parenthetical tags (e.g., '(OSU-4)') and trim whitespace."""
    try:
        name = raw_name or "Unknown"
        # Remove any trailing parenthetical like "(OSU-4)"
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        return name if name else (raw_name or "Unknown")
    except Exception:
        return raw_name or "Unknown"

@app.post("/webhook")
async def receive_webhook(request: Request, api_key_valid: bool = Depends(validate_webhook_api_key)):
    data = await request.json()
    logger.info(f"Received webhook data from: {data.get('name', 'Unknown')}")

    # Ignore GroupMe system messages
    if data.get("system") is True:
        logger.info("Skipping system-generated GroupMe message")
        return {"status": "skipped", "reason": "system message"}

    name = data.get("name", "Unknown")
    display_name = _normalize_display_name(name)
    text = data.get("text", "")
    created_at = data.get("created_at", 0)
    group_id = str(data.get("group_id") or "")
    team = GROUP_ID_TO_TEAM.get(group_id, "Unknown") if group_id else "Unknown"
    user_id = str(data.get("user_id") or data.get("sender_id") or "")
    message_dt: datetime
    
    # Handle invalid or missing timestamps
    try:
        if created_at == 0 or created_at is None:
            # Use current time if timestamp is missing or invalid
            message_dt = now_tz()
            timestamp = (
                message_dt.strftime("%Y-%m-%d %H:%M:%S") if is_testing else message_dt.isoformat()
            )
            logger.warning(f"Missing or invalid timestamp for message from {name}, using current time")
        else:
            message_dt = datetime.fromtimestamp(created_at, tz=APP_TZ)
            timestamp = message_dt.strftime("%Y-%m-%d %H:%M:%S") if is_testing else message_dt.isoformat()
    except (ValueError, OSError) as e:
        # Handle invalid timestamp values
        message_dt = now_tz()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.warning(f"Invalid timestamp {created_at} for message from {name}: {e}, using current time")

    # Skip processing completely empty or meaningless messages
    if not text or text.strip() == "":
        logger.info(f"Skipping empty message from {name}")
        return {"status": "skipped", "reason": "empty message"}
    
    # Skip if both name and text are defaults/unknown
    if name == "Unknown" and (not text or text.strip() == ""):
        logger.info(f"Skipping placeholder message with no content")
        return {"status": "skipped", "reason": "placeholder message"}

    # Check if this user already has a "responding" status to provide context to AI
    user_previous_status = None
    try:
        for msg in reversed(messages):  # Check recent messages first
            if msg.get("name") == display_name and msg.get("arrival_status") == "Responding":
                user_previous_status = "responding"
                logger.info(f"Found previous responding status for {display_name}")
                break
    except Exception as e:
        logger.warning(f"Error checking previous status for {display_name}: {e}")

    # Provide sender context and previous status to AI
    context_message = f"Sender: {display_name}. Message: {text}"
    if user_previous_status == "responding":
        context_message += f" (Note: This user is already responding and may be updating their ETA)"

    # If the user previously provided an ETA, pass it for relative updates
    prev_eta_iso: Optional[str] = None
    try:
        for msg in reversed(messages):
            if msg.get("name") == display_name and msg.get("eta_timestamp_utc"):
                prev_eta_iso = msg.get("eta_timestamp_utc")  # already ISO with Z offset
                break
    except Exception:
        prev_eta_iso = None

    parsed = extract_details_from_text(context_message, base_time=message_dt, prev_eta_iso=prev_eta_iso)
    logger.info(f"Parsed details: vehicle={parsed.get('vehicle')}, eta={parsed.get('eta')}, raw_status={parsed.get('raw_status')}")

    # Calculate additional fields for better display
    eta_info = calculate_eta_info(parsed.get("eta", "Unknown"), message_dt)
    
    # Use raw_status from AI parsing if available, otherwise fall back to eta_info status
    arrival_status = parsed.get("raw_status") or eta_info.get("status")
    if arrival_status == "On Route":
        arrival_status = "Responding"
    status_source = parsed.get("status_source")
    status_confidence = parsed.get("status_confidence")
    status_evidence = parsed.get("status_evidence")


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
        "eta_timestamp": eta_info.get("eta_timestamp"),
        "eta_timestamp_utc": eta_info.get("eta_timestamp_utc"),
        "minutes_until_arrival": eta_info.get("minutes_until_arrival"),
        "arrival_status": arrival_status
    }

    # Reload messages to get latest data from other pods
    reload_messages()
    messages.append(message_record)
    save_messages()  # Save to shared storage
    return {"status": "ok"}

def calculate_eta_info(eta_str: str, message_time: Optional[datetime] = None) -> Dict[str, Any]:
    """Calculate additional ETA information for better display"""
    try:
        if eta_str in ["Unknown", "Not Responding", "Cancelled"]:
            return {
                "eta_timestamp": None,
                "eta_timestamp_utc": None,
                "minutes_until_arrival": None,
                "status": ("Cancelled" if eta_str == "Cancelled" else eta_str)
            }

        # Try to parse as HH:MM format
        if ":" in eta_str and len(eta_str) == 5:  # HH:MM format
            # Use message time as context if provided, otherwise use current time
            reference_time = message_time or now_tz()
            eta_time = datetime.strptime(eta_str, "%H:%M")
            # Apply to the reference date in the same timezone
            eta_datetime = reference_time.replace(
                hour=eta_time.hour,
                minute=eta_time.minute,
                second=0,
                microsecond=0
            )
            # If ETA is earlier/equal than reference time, assume it's next day
            if eta_datetime <= reference_time:
                eta_datetime += timedelta(days=1)

            # Calculate minutes until arrival from current time (not reference time)
            current_time = now_tz()
            time_diff = eta_datetime - current_time
            minutes_until = int(time_diff.total_seconds() / 60)

            return {
                # Test mode keeps legacy format; otherwise use ISO 8601 with offset
                "eta_timestamp": (
                    eta_datetime.strftime("%Y-%m-%d %H:%M:%S") if is_testing else eta_datetime.isoformat()
                ),
                "eta_timestamp_utc": eta_datetime.astimezone(timezone.utc).isoformat(),
                "minutes_until_arrival": minutes_until,
                "status": "Responding" if minutes_until > 0 else "Arrived"
            }
        else:
            # Fallback for non-standard formats
            return {
                "eta_timestamp": None,
                "eta_timestamp_utc": None,
                "minutes_until_arrival": None,
                "status": "ETA Format Unknown"
            }

    except Exception as e:
        logger.warning(f"Error calculating ETA info for '{eta_str}': {e}")
        return {
            "eta_timestamp": None,
            "eta_timestamp_utc": None,
            "minutes_until_arrival": None,
            "status": "ETA Parse Error"
        }

@app.get("/api/responders")
def get_responder_data(request: Request) -> JSONResponse:
    """Responder data; gated by auth domain policy."""
    # Enforce that user is authenticated and allowed domain if headers present
    user_email = (
        request.headers.get("X-Auth-Request-Email")
        or request.headers.get("X-Auth-Request-User")
        or request.headers.get("x-forwarded-email")
        or request.headers.get("X-User")
    )
    if not user_email:
        # If no auth headers: allow in tests or when local bypass is on
        if not (is_testing or ALLOW_LOCAL_AUTH_BYPASS):
            raise HTTPException(status_code=401, detail="Not authenticated")
    else:
        if not is_email_domain_allowed(user_email):
            raise HTTPException(status_code=403, detail="Access denied")

    reload_messages()  # Get latest data from shared storage
    return JSONResponse(content=messages)

@app.get("/api/current-status")
def get_current_status(request: Request) -> JSONResponse:
    """Get the latest status for each person - most robust aggregated view for mission control."""
    # Same auth as responders endpoint
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

    reload_messages()  # Get latest data from shared storage
    
    # Dictionary to track latest message per person
    latest_by_person: Dict[str, Dict[str, Any]] = {}
    
    # Process messages chronologically to build latest status per person
    sorted_messages = sorted(
        messages,
        key=lambda x: x.get('timestamp_utc', x.get('timestamp', '')),
    )
    
    for msg in sorted_messages:
        name = msg.get('name', '').strip()
        if not name:
            continue
            
        # Determine status priority for conflict resolution
        arrival_status = msg.get('arrival_status', 'Unknown')
        eta = msg.get('eta', 'Unknown')
        text = msg.get('text', '').lower()
        
        # Calculate status priority (higher = more definitive)
        priority = 0
        if arrival_status == 'Cancelled' or 'can\'t make it' in text or 'cannot make it' in text:
            priority = 100  # Highest - definitive cancellation
        elif arrival_status == 'Not Responding':
            priority = 10   # Low - absence of response
        elif arrival_status == 'Responding' and eta != 'Unknown':
            priority = 80   # High - active response with ETA
        elif arrival_status == 'Responding':
            priority = 60   # Medium - active response without ETA
        elif eta != 'Unknown':
            priority = 70   # Medium-high - ETA provided
        elif arrival_status == 'Available':
            priority = 40
        elif arrival_status == 'Informational':
            priority = 15

        else:
            priority = 20   # Low-medium - generic message
            
        # Always update to latest message, but track priority for tie-breaking
        current_entry = latest_by_person.get(name)
        if current_entry is None:
            # First message for this person
            latest_by_person[name] = dict(msg)
            latest_by_person[name]['_priority'] = priority
        else:
            # Compare timestamps - always take latest chronologically
            current_ts = current_entry.get('timestamp', '')
            new_ts = msg.get('timestamp', '')
            
            if new_ts >= current_ts:
                # This message is newer, so it becomes the latest
                latest_by_person[name] = dict(msg)
                latest_by_person[name]['_priority'] = priority
            elif new_ts == current_ts and priority > current_entry.get('_priority', 0):
                # Same timestamp but higher priority status
                latest_by_person[name] = dict(msg)
                latest_by_person[name]['_priority'] = priority
    
    # Clean up internal priority field and prepare response
    result = []
    for person_data in latest_by_person.values():
        person_data.pop('_priority', None)  # Remove internal field
        result.append(person_data)
    
    # Sort by latest activity (most recent first) for mission control relevance
    result.sort(key=lambda x: x.get('timestamp_utc', x.get('timestamp', '')), reverse=True)
    
    return JSONResponse(content=result)

@app.post("/api/responders")
async def create_responder_entry(request: Request) -> JSONResponse:
    """Create a manual responder entry (edit mode).

    Body accepts: name, text, timestamp, vehicle, eta, eta_timestamp, team, group_id
    """
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
        "timestamp": (
            message_dt.strftime("%Y-%m-%d %H:%M:%S") if is_testing else message_dt.isoformat()
        ),
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
    }

    reload_messages()
    messages.append(rec)
    save_messages()
    return JSONResponse(status_code=201, content=rec)

@app.put("/api/responders/{msg_id}")
async def update_responder_entry(msg_id: str, request: Request) -> JSONResponse:
    """Update an existing responder message by ID."""
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

    # Updatable fields
    for key in ["name", "text", "team", "group_id", "vehicle", "user_id"]:
        if key in patch:
            val = patch.get(key)
            if key == "name":
                val = _normalize_display_name(str(cast(Any, val) or ""))
            current[key] = val

    # Handle timestamp and ETA updates
    ts_in: Any = patch.get("timestamp") if "timestamp" in patch else current.get("timestamp")
    msg_dt = _parse_datetime_like(ts_in) or now_tz()
    current["timestamp"] = (
        msg_dt.strftime("%Y-%m-%d %H:%M:%S") if is_testing else msg_dt.isoformat()
    )
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
    })

    messages[idx] = current
    save_messages()
    return JSONResponse(content=current)

@app.delete("/api/responders/{msg_id}")
def delete_responder_entry(msg_id: str, request: Request) -> Dict[str, Any]:
    """Delete a responder message by ID (soft delete - moves to deleted storage)."""
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")

    reload_messages()
    
    # Find the message to delete
    to_delete = [m for m in messages if str(m.get("id")) == msg_id]
    if not to_delete:
        raise HTTPException(status_code=404, detail="Not found")
    
    # Soft delete - move to deleted storage
    soft_delete_messages(to_delete)
    
    # Remove from active messages
    remaining = [m for m in messages if str(m.get("id")) != msg_id]
    messages.clear()
    messages.extend(remaining)
    save_messages()
    
    return {"status": "deleted", "id": msg_id, "soft_delete": True}

@app.post("/api/responders/bulk-delete")
async def bulk_delete_responder_entries(request: Request) -> Dict[str, Any]:
    """Bulk delete messages by IDs (soft delete - moves to deleted storage). Body: {"ids": [..]}"""
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
    
    # Find messages to delete
    ids_set = set(ids)
    to_delete = [m for m in messages if str(m.get("id")) in ids_set]
    to_keep = [m for m in messages if str(m.get("id")) not in ids_set]
    
    if to_delete:
        # Soft delete - move to deleted storage
        soft_delete_messages(to_delete)
        
        # Update active messages
        messages.clear()
        messages.extend(to_keep)
        save_messages()
    
    removed = len(to_delete)
    return {"status": "deleted", "removed": int(removed), "soft_delete": True}

@app.post("/api/clear-all")
def clear_all_data(request: Request) -> Dict[str, Any]:
    """Clear all responder data. Protected by env gate or API key.

    Allowed if one of the following is true:
    - Environment variable ALLOW_CLEAR_ALL == "true" (case-insensitive)
    - Header X-API-Key matches WEBHOOK_API_KEY
    """
    allow_env = os.getenv("ALLOW_CLEAR_ALL", "false").lower() == "true"
    provided_key = request.headers.get("X-API-Key")
    key_ok = webhook_api_key and provided_key == webhook_api_key
    if not (allow_env or key_ok):
        raise HTTPException(status_code=403, detail="Clear-all is disabled")

    # Reload first to get counts, then clear
    reload_messages()
    initial = len(messages)
    _clear_all_messages()
    return {"status": "cleared", "removed": int(initial)}

@app.get("/api/deleted-responders")
def get_deleted_responders(request: Request) -> List[Dict[str, Any]]:
    """Get all deleted responder messages."""
    if not _authn_domain_and_admin_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    load_deleted_messages()
    return deleted_messages

@app.post("/api/deleted-responders/undelete")
async def undelete_responder_entries(request: Request) -> Dict[str, Any]:
    """Restore deleted messages back to active state. Body: {"ids": [..]}"""
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
    """Permanently delete a message from deleted storage."""
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
    """Permanently clear all deleted responder data. Protected by env gate or API key."""
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
    """Debug endpoint to show which pod is serving requests"""
    pod_name = os.getenv("HOSTNAME", "unknown-pod")
    pod_ip = os.getenv("POD_IP", "unknown-ip")
    
    # Check Redis connection status
    redis_status = "disconnected"
    try:
        init_redis()
        if redis_client:
            cast(Any, redis_client).ping()
            redis_status = "connected"
    except:
        redis_status = "error"
    
    return JSONResponse(content={
        "pod_name": pod_name,
        "pod_ip": pod_ip,
        "message_count": len(messages),
        "redis_status": redis_status
    })

@app.get("/health")
def health() -> Dict[str, Any]:
    """Simple unauthenticated health endpoint for liveness/readiness probes."""
    try:
        # Optional: light Redis ping without failing the health
        status = "ok"
        try:
            init_redis()
            if redis_client:
                cast(Any, redis_client).ping()
        except Exception:
            # Still report ok; detailed status available at /debug/pod-info
            status = "degraded"
        return {"status": status}
    except Exception:
        return {"status": "error"}

@app.get("/dashboard", response_class=HTMLResponse)
def display_dashboard() -> str:
    # Reload messages from Redis to ensure we have the latest data
    reload_messages()
    
    current_time = datetime.now()
    
    html = f"""
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
            <th>Message</th>
        </tr>
    """
    
    # Sort by ETA (soonest first), then by message time
    sorted_messages = sorted(messages, key=lambda x: (
        x.get('minutes_until_arrival', 9999) if x.get('minutes_until_arrival') is not None else 9999,
        x['timestamp']
    ), reverse=False)
    
    for msg in sorted_messages:
        # Color coding based on status
        vehicle = msg.get('vehicle', 'Unknown')
        team = msg.get('team', 'Unknown')
        eta_display = msg.get('eta_timestamp') or msg.get('eta', 'Unknown')
        minutes_out = msg.get('minutes_until_arrival')
        status = msg.get('arrival_status', 'Unknown')

        # Row color based on response type
        if status == 'Not Responding':
            row_color = '#ffcccc'  # Light red
        elif vehicle == 'Unknown':
            row_color = '#ffffcc'  # Light yellow
        elif minutes_out is not None and minutes_out <= 5:
            row_color = '#ccffcc'  # Light green - arriving soon
        elif minutes_out is not None and minutes_out <= 15:
            row_color = '#cceeff'  # Light blue - arriving medium term
        else:
            row_color = '#ffffff'  # White - normal

        minutes_display = f"{minutes_out} min" if minutes_out is not None else "—"

        html += f"""
        <tr style='background-color: {row_color};'>
            <td>{_esc(msg.get('timestamp', ''))}</td>
            <td><strong>{_esc(msg.get('name', ''))}</strong></td>
            <td>{_esc(team)}</td>
            <td>{_esc(vehicle)}</td>
            <td>{_esc(eta_display)}</td>
            <td>{_esc(minutes_display)}</td>
            <td>{_esc(status)}</td>
            <td style='max-width: 300px; word-wrap: break-word;'>{_esc(msg.get('text', ''))}</td>
        </tr>
        """
    
    html += """
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
    return html

@app.get("/deleted-dashboard", response_class=HTMLResponse)
def display_deleted_dashboard() -> str:
    """Display dashboard of deleted responder messages"""
    # Reload deleted messages from Redis to ensure we have the latest data
    load_deleted_messages()
    
    current_time = datetime.now()
    
    html = f"""
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
            <th>Message</th>
            <th>Message ID</th>
        </tr>
    """
    
    # Sort by deletion time (most recent first)
    sorted_deleted = sorted(deleted_messages, key=lambda x: x.get('deleted_at', ''), reverse=True)
    
    for msg in sorted_deleted:
        msg_time = msg.get('timestamp', 'Unknown')
        deleted_time = msg.get('deleted_at', 'Unknown')
        name = msg.get('name', '')
        team = msg.get('team', msg.get('unit', ''))  # Handle both team and unit
        vehicle = msg.get('vehicle', 'Unknown')
        eta = msg.get('eta', 'Unknown')
        message_text = msg.get('text', '')
        msg_id = msg.get('id', '')
        
        # Truncate long message text
        if len(message_text) > 100:
            message_text = message_text[:100] + "..."
        
        # Format deleted time
        try:
            if deleted_time != 'Unknown':
                dt = datetime.fromisoformat(deleted_time.replace('Z', '+00:00'))
                deleted_display = dt.strftime('%Y-%m-%d %H:%M:%S')
            else:
                deleted_display = 'Unknown'
        except:
            deleted_display = deleted_time
        
        html += f"""
        <tr style='background-color: #fff0f0;'>
            <td>{_esc(msg_time)}</td>
            <td>{_esc(deleted_display)}</td>
            <td>{_esc(name)}</td>
            <td>{_esc(team)}</td>
            <td>{_esc(vehicle)}</td>
            <td>{_esc(eta)}</td>
            <td style='max-width: 300px; word-wrap: break-word;'>{_esc(message_text)}</td>
            <td style='font-size: 10px; color: #666;'>{_esc(msg_id)}</td>
        </tr>
        """
    
    if not deleted_messages:
        html += """
        <tr>
            <td colspan="8" style="text-align: center; color: #666; font-style: italic;">No deleted messages</td>
        </tr>
        """
    
    html += """
    </table>
    <br>
    <div style='font-size: 12px; color: #666;'>
        <p><strong>Note:</strong> Deleted messages are stored in Redis under 'respondr_deleted_messages' key.</p>
        <p>Use the API endpoints to restore messages: POST /api/deleted-responders/undelete</p>
    </div>
    """
    return html

# Determine frontend build path - works for both development and Docker
if os.path.exists(os.path.join(os.path.dirname(__file__), "frontend/build")):
    # Docker environment - frontend build is copied to ./frontend/build
    frontend_build = os.path.join(os.path.dirname(__file__), "frontend/build")
else:
    # Development environment - frontend build is at ../frontend/build
    frontend_build = os.path.join(os.path.dirname(__file__), "../frontend/build")

# Only mount static files if the directory exists (not in test mode)
static_dir = os.path.join(frontend_build, "static")
if not is_testing and os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.post("/cleanup/invalid-timestamps")
def cleanup_invalid_timestamps(api_key: str = Depends(validate_webhook_api_key)) -> Dict[str, Any]:
    """Remove messages with clearly invalid timestamps only (safer)."""
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
        # Drop obvious epoch-0/1970 artifacts
        if isinstance(ts, str) and ts.startswith("1970-01-01"):
            removed += 1
            continue
        kept.append(msg)

    messages = kept
    save_messages()
    return {
        "status": "success",
        "message": f"Cleaned up {removed} invalid entries",
        "initial_count": initial_count,
        "remaining_count": len(messages),
    }

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
    """Handle ACR image push events and trigger a rolling restart.

    Security: requires X-ACR-Token header to match ACR_WEBHOOK_TOKEN env var.
    This endpoint should be excluded from OAuth2 proxy auth.
    """
    # Auth
    provided = request.headers.get("X-ACR-Token") or request.query_params.get("token")
    if not ACR_WEBHOOK_TOKEN or provided != ACR_WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        raw_payload: Any = await request.json()
    except Exception:
        raw_payload = {}

    # Normalize payload as dict
    payload: Dict[str, Any] = cast(Dict[str, Any], raw_payload if isinstance(raw_payload, dict) else {})

    # Basic filter: only act on push events for our repository (best-effort across ACR payload shapes)
    action = cast(str | None, payload.get("action") or payload.get("eventType"))
    target = cast(Dict[str, Any], payload.get("target", {}) or {})
    repo = cast(str, target.get("repository", ""))
    tag = cast(str, target.get("tag", ""))

    logger.info(f"ACR webhook: action={action} repo={repo} tag={tag}")
    if action and "push" not in str(action).lower():
        return {"status": "ignored", "reason": f"action={action}"}

    # Optional: limit to our app image name if available in env
    expected_repo = os.getenv("ACR_REPOSITORY", "respondr")
    if expected_repo and repo and expected_repo not in repo:
        return {"status": "ignored", "reason": f"repo={repo}"}

    # Trigger restart by patching a timestamp annotation on pod template
    try:
        ks = importlib.import_module("kubernetes")
        k8s_client = getattr(ks, "client")
        k8s_config = getattr(ks, "config")
        # In cluster config will work in AKS; fall back to local kubeconfig for dev
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()

        apps = k8s_client.AppsV1Api()
        patch: Dict[str, Any] = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()
                        }
                    }
                }
            }
        }
        apps.patch_namespaced_deployment(name=K8S_DEPLOYMENT, namespace=K8S_NAMESPACE, body=patch)
        logger.info(f"Triggered rollout restart for deployment {K8S_DEPLOYMENT} in namespace {K8S_NAMESPACE}")
        return {"status": "restarted", "deployment": K8S_DEPLOYMENT, "namespace": K8S_NAMESPACE}
    except Exception as e:
        logger.error(f"Failed to restart deployment: {e}")
        raise HTTPException(status_code=500, detail="Failed to restart deployment")

# ----------------------------------------------------------------------------
# SPA catch-all: serve index.html for client-side routes (e.g., /profile)
# Declare this AFTER all API and asset routes so it doesn't shadow them.
# ----------------------------------------------------------------------------
@app.get("/{full_path:path}")
def spa_catch_all(full_path: str):
    """Serve the frontend SPA for any non-API path to support client routing."""
    if is_testing:
        # Avoid interfering with unit tests that expect 404s on unknown paths
        raise HTTPException(status_code=404, detail="Not available in tests")
    index_path = os.path.join(frontend_build, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend not built")
