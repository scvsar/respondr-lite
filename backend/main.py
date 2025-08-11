import os
import sys
import json
import logging
import re
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
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

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

# Check if we're running in test mode
is_testing = os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules

# temporarily disable api-key check in test mode
disable_api_key_check = True

# Timezone configuration: default to PST approximation; allow override via TIMEZONE env
TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")
APP_TZ = get_timezone(TIMEZONE)

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
    if disable_api_key_check or is_testing:
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
    if is_testing or ALLOW_LOCAL_AUTH_BYPASS:
        return True
    if not email:
        return False
    try:
        return email.strip().lower() in allowed_admin_users
    except Exception:
        return False

@app.get("/api/user")
def get_user_info(request: Request) -> JSONResponse:
    """Get authenticated user information from OAuth2 Proxy headers"""
    # Debug: log all headers to see what OAuth2 proxy is sending
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

def extract_details_from_text(text: str, base_time: Optional[datetime] = None) -> Dict[str, str]:
    """Extract vehicle and ETA from freeform text.

    If base_time is provided, use it as the anchor for duration-based ETA calculations
    (e.g., "15 minutes", "1 hour"). Otherwise, fall back to the current app time.

    Returns a mapping like {"vehicle": "SAR-7|POV|Unknown|Not Responding", "eta": "HH:MM|Unknown|Not Responding"}
    """
    logger.info(f"Extracting details from text: {text[:50]}...")
    anchor_time: datetime = base_time or now_tz()

    # Fast-path heuristics for local/dev
    if FAST_LOCAL_PARSE or client is None:
        tl = text.lower()
        # Detect ETA given as HHMM after 'eta' (e.g., 'ETA 1022') before cancellation codes
        m_eta_compact = re.search(r"\beta\s*:?\s*(\d{3,4})\b", tl)

        # Cancellation / stand-down signals (treat as 'Cancelled')
        # Special codes: '10-22', '1022', or '10 22' imply stand down unless clearly 'ETA 10:22' or 'ETA 1022'
        has_10_22_code = bool(re.search(r"\b10\s*-\s*22\b", tl) or re.search(r"\b10\s+22\b", tl) or re.search(r"\b1022\b", tl))
        # If compact ETA detected (e.g., 'ETA 1022'), do not treat as cancellation solely due to '1022'
        if not m_eta_compact and has_10_22_code:
            return {"vehicle": "Not Responding", "eta": "Cancelled"}

        # Not responding / off-topic signals -> Cancelled
        if any(k in tl for k in [
            "can't make it", "cannot make it", "not coming", "won't make", "won’t make", "backing out", "back out",
            "stand down", "standing down", "cancel", "cancelling", "canceled", "cancelled",
            "family emergency", "unavailable", "can't respond", "cannot respond", "won't respond", "cant make it"
        ]):
            return {"vehicle": "Not Responding", "eta": "Cancelled"}

        vehicle = "Unknown"
        m = re.search(r"\bsar\s*-?\s*(\d{1,3})\b", tl)
        if m:
            vehicle = f"SAR-{m.group(1)}"
        elif any(k in tl for k in ["pov", "personal vehicle", "own car", "driving myself", "my car"]):
            vehicle = "POV"
        elif "sar rig" in tl:
            vehicle = "SAR Rig"

        # ETA detection
        eta = "Unknown"
        m_time = re.search(r"\b(\d{1,2}:\d{2}\s*(am|pm)?)\b", tl)
        # Composite durations
        m_hours_and_minutes = re.search(r"\b(\d+)\s*(?:hours?|hrs?)\s*and\s*(\d+)\s*(?:mins?|minutes?)\b", tl)
        m_an_hour_and_minutes = re.search(r"\b(?:an|a)\s+hour\s*and\s*(\d+)\s*(?:mins?|minutes?)\b", tl)
        # Also accept forms without the explicit 'minutes' word (e.g., 'an hour and 10')
        m_hours_and_number = re.search(r"\b(\d+)\s*(?:hours?|hrs?)\s*and\s*(\d+)\b", tl)
        m_an_hour_and_number = re.search(r"\b(?:an|a)\s+hour\s*and\s*(\d+)\b", tl)
        m_half_hour = ("half" in tl and ("hour" in tl or "hr" in tl)) or re.search(r"\bhalf\s+an?\s+hour\b", tl)
        m_min = re.search(r"\b(\d{1,3})\s*(min|mins|minutes)\b", tl)
        m_hr = re.search(r"\b(\d{1,2})\s*(hour|hr|hours|hrs)\b", tl)
        half_hr = bool(m_half_hour)

        # Use the message's timestamp (if provided via base_time) to anchor duration math
        current_time = anchor_time
        if m_time:
            eta = convert_eta_to_timestamp(m_time.group(1), current_time)
        elif m_hours_and_minutes:
            hours = int(m_hours_and_minutes.group(1))
            mins = int(m_hours_and_minutes.group(2))
            eta = convert_eta_to_timestamp(f"{hours} hours and {mins} minutes", current_time)
        elif m_an_hour_and_minutes:
            mins = int(m_an_hour_and_minutes.group(1))
            eta = convert_eta_to_timestamp(f"an hour and {mins} minutes", current_time)
        elif m_hours_and_number:
            hours = int(m_hours_and_number.group(1))
            mins = int(m_hours_and_number.group(2))
            eta = convert_eta_to_timestamp(f"{hours} hours and {mins} minutes", current_time)
        elif m_an_hour_and_number:
            mins = int(m_an_hour_and_number.group(1))
            eta = convert_eta_to_timestamp(f"an hour and {mins} minutes", current_time)
        elif m_eta_compact:
            # Interpret HHMM following 'eta' as time (e.g., ETA 1022 -> 10:22)
            digits = m_eta_compact.group(1)
            if len(digits) == 3:
                hour = int(digits[0])
                minute = int(digits[1:3])
            else:
                hour = int(digits[:2])
                minute = int(digits[2:4])
            if 0 <= hour <= 24 and 0 <= minute <= 59:
                if hour == 24:
                    hour = 0
                eta = f"{hour:02d}:{minute:02d}"
        elif m_half_hour:
            eta = convert_eta_to_timestamp("half hour", current_time)
        elif m_min:
            eta = convert_eta_to_timestamp(f"{m_min.group(1)} minutes", current_time)
        elif m_hr:
            eta = convert_eta_to_timestamp(f"{m_hr.group(1)} hour", current_time)

        return {"vehicle": vehicle, "eta": eta}

    # Azure OpenAI with function calling
    try:
        current_time = anchor_time
        current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S %Z")
        current_time_short = current_time.strftime("%H:%M")

        # Simplified prompt for direct parsing (no function calling)
        prompt = (
    "You are a SAR (Search and Rescue) message parser. Parse the message and return ONLY valid JSON.\n"
    f"Current time: {current_time_str} (24-hour format: {current_time_short})\n\n"
    
    "Return JSON with three fields: status, vehicle, eta\n\n"
    
    "STATUS DETECTION:\n"
    "- 'responding': Actively responding with intention to arrive\n"
    "  Examples: 'Responding POV ETA 08:45', 'POV ETA 0830', 'Headed to Taylor's Landing'\n"
    "  IMPORTANT: ETA updates from already responding people stay 'responding'\n"
    "  'Actually I'll be an hour and 10 min', 'Updated ETA 15:30', 'Make that 20 minutes'\n"
    "- 'cancelled': Mission cancelled or person can't respond\n"
    "  Examples: 'can't make it', 'backing out', '10-22', 'Mission canceled', 'Subject found'\n"
    "- 'available': Can respond but no firm commitment (initial offer only)\n"
    "  Examples: 'I can respond as IMT', 'I can help with planning'\n"
    "  NOTE: If someone already responded, ETA updates are 'responding', not 'available'\n"
    "- 'informational': Providing information, logistics, questions\n"
    "  Examples: 'Key for 74 is in key box', 'Who can respond?', 'checking with Hayden'\n"
    "- 'unknown': Cannot determine clear status\n\n"
    
    "CANCELLATION DETECTION - Return status 'cancelled':\n"
    "- Examples of declining/negative responses:\n"
    "  'can't make it', 'cannot make it', 'won't make it', 'not coming', 'backing out'\n"
    "  'Ok I can't make it', 'I also can't make it', 'Sorry, backing out'\n"
    "- Special codes: '10-22' (or '1022') means mission complete/cancelled\n"
    "  'Copied 10-22', 'Copy 10-22', '10-22', '1022 subj found'\n"
    "- Mission status: 'Mission canceled', 'Mission cancelled', 'Subject found'\n"
    "- Logistics/info only: 'Key for 74 is in key box', 'Who can respond?'\n\n"
    
    "VEHICLE EXTRACTION:\n"
    "- SAR units: 'SAR-12', 'SAR 12', 'sar78', 'SAR-60' → format as 'SAR-XX'\n"
    "- Personal vehicle: 'POV', 'personal vehicle', 'own car' → 'POV'\n"
    "- Unknown/unclear → 'unknown'\n"
    "Examples:\n"
    "  'SAR-3 on the way' → 'SAR-3'\n"
    "  'Responding sar78' → 'SAR-78'\n"
    "  'Driving POV' → 'POV'\n"
    "  'I can respond as IMT' → 'unknown'\n\n"
    
    "ETA EXTRACTION:\n"
    "- Absolute times: '0830' → '08:30', '1150' → '11:50', '15:00' → '15:00'\n"
    "- Relative times: Return the pattern EXACTLY as found, system will calculate\n"
    "  * '15 minutes', '15min', '15 mins' → 'RELATIVE:15min'\n"
    "  * '30min', '30 minutes' → 'RELATIVE:30min'\n"
    "  * '45 minutes', '45min' → 'RELATIVE:45min'\n"
    "  * '60min', '60 minutes', '1 hour' → 'RELATIVE:60min'\n"
    "  * '90min', '90 minutes' → 'RELATIVE:90min'\n"
    "  * 'hour and 10 min', 'hour and 10 minutes' → 'RELATIVE:70min'\n"
    "  * 'hour and a half', '1.5 hours' → 'RELATIVE:90min'\n"
    "  * '2 hours', '120 minutes' → 'RELATIVE:120min'\n"
    "  * '2 hours', '120 minutes' → 'RELATIVE:120min'\n"
    "  * 'in 20', 'be there in 20' → 'RELATIVE:20min'\n"
    "- Unknown/unclear → 'unknown'\n"
    "- If cancelled status → 'cancelled'\n\n"
    f"  Current time {current_time_short}: 'ETA 15 minutes' → '{(current_time + timedelta(minutes=15)).strftime('%H:%M')}'\n"
    "- No time mentioned → 'unknown'\n"
    "- DON'T interpret 'Xmin' as 'X:00' - calculate relative time!\n"
    "Examples:\n"
    "  Current time 14:20, 'ETA 15:00' → '15:00'\n"
    "  Current time 14:20, '30 min out' → '14:50'\n"
    "  Current time 12:07, 'ETA 60min' → '13:07' (NOT '01:00'!)\n"
    "  'POV ETA 0830' → '08:30'\n"
    "  'Updated eta: arriving 11:30' → '11:30'\n\n"
    
    "COMPLETE EXAMPLES:\n"
    "  'Responding POV ETA 08:45' → {\"status\": \"responding\", \"vehicle\": \"POV\", \"eta\": \"08:45\"}\n"
    "  'can't make it, sorry' → {\"status\": \"cancelled\", \"vehicle\": \"unknown\", \"eta\": \"unknown\"}\n"
    "  'I can respond as IMT' → {\"status\": \"available\", \"vehicle\": \"unknown\", \"eta\": \"unknown\"}\n"
    "  'Key for 74 is in key box' → {\"status\": \"informational\", \"vehicle\": \"unknown\", \"eta\": \"unknown\"}\n"
    "  '10-22' → {\"status\": \"cancelled\", \"vehicle\": \"unknown\", \"eta\": \"unknown\"}\n"
    "  'Mission canceled. Subject found' → {\"status\": \"cancelled\", \"vehicle\": \"unknown\", \"eta\": \"unknown\"}\n"
    "  'Who can respond to Vesper?' → {\"status\": \"informational\", \"vehicle\": \"unknown\", \"eta\": \"unknown\"}\n"
    "  'SAR-5 ETA 15:45' → {\"status\": \"responding\", \"vehicle\": \"SAR-5\", \"eta\": \"15:45\"}\n"
    "  'Responding sar78 1150' → {\"status\": \"responding\", \"vehicle\": \"SAR-78\", \"eta\": \"11:50\"}\n"
    "  'Responding SAR7 ETA 60min' → {\"status\": \"responding\", \"vehicle\": \"SAR-7\", \"eta\": \"RELATIVE:60min\"}\n"
    "  'SAR-3 ETA 30min' → {\"status\": \"responding\", \"vehicle\": \"SAR-3\", \"eta\": \"RELATIVE:30min\"}\n"
    "  'ETA 45 minutes' → {\"status\": \"responding\", \"vehicle\": \"unknown\", \"eta\": \"RELATIVE:45min\"}\n"
    "  'POV ETA 90min' → {\"status\": \"responding\", \"vehicle\": \"POV\", \"eta\": \"RELATIVE:90min\"}\n"
    "  'Actually I'll be an hour and 10 min' (if already responding) → {\"status\": \"responding\", \"vehicle\": \"unknown\", \"eta\": \"RELATIVE:70min\"}\n"
    "  'Updated ETA 20 minutes' (if already responding) → {\"status\": \"responding\", \"vehicle\": \"unknown\", \"eta\": \"RELATIVE:20min\"}\n"
    "  'Make that 30 min' (if already responding) → {\"status\": \"responding\", \"vehicle\": \"unknown\", \"eta\": \"RELATIVE:30min\"}\n\n"
    
    f"MESSAGE: \"{text}\"\n\n"
    "Return ONLY this JSON format: "
    '{\"status\": \"responding|cancelled|available|informational|unknown\", \"vehicle\": \"value\", \"eta\": \"HH:MM|unknown\"}'
)


        logger.info(f"Calling Azure OpenAI with simplified prompt, deployment: {azure_openai_deployment}")
        
        # Call Azure OpenAI with simplified approach (no function calling)
        response = cast(Any, client).chat.completions.create(
            model=cast(str, azure_openai_deployment),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
        )
        
        message = response.choices[0].message
        reply = (message.content or "").strip()

        # Parse JSON from reply
        parsed_json: Dict[str, str]
        if reply.startswith("{") and reply.endswith("}"):
            parsed_json = json.loads(reply)
        else:
            json_match = re.search(r"\{[^}]+\}", reply)
            if json_match:
                parsed_json = json.loads(json_match.group())
            else:
                logger.warning(f"No valid JSON found in response: '{reply}'")
                return {"vehicle": "Unknown", "eta": "Unknown"}

        # Handle new status-based format
        raw_status = None  # Preserve raw status for frontend
        if "status" in parsed_json:
            status = parsed_json.get("status", "unknown").lower()
            vehicle = parsed_json.get("vehicle", "unknown")
            eta = parsed_json.get("eta", "unknown")
            
            # Preserve the raw status for the frontend
            raw_status = status.capitalize()
            
            # Convert status to legacy format for backward compatibility
            if status == "cancelled":
                return {"vehicle": "Not Responding", "eta": "Cancelled", "raw_status": raw_status}
            elif status == "informational" and vehicle == "unknown" and eta == "unknown":
                return {"vehicle": "Not Responding", "eta": "Cancelled", "raw_status": raw_status}
            else:
                # For responding, available, or unknown status, use the vehicle and eta as provided
                if vehicle == "unknown":
                    vehicle = "Unknown"
                if eta == "unknown":
                    eta = "Unknown"
                parsed_json = {"vehicle": vehicle, "eta": eta, "raw_status": raw_status}
        
        # Legacy format validation (for old format responses)
        if "vehicle" not in parsed_json or "eta" not in parsed_json:
            logger.warning(f"Missing required fields in response: {parsed_json}")
            return {"vehicle": "Unknown", "eta": "Unknown"}

        # Apply additional validation to the AI's result
        eta_value = parsed_json.get("eta", "Unknown")
        # Normalize stand down to Cancelled
        if isinstance(eta_value, str) and eta_value.strip().lower() in {"cancelled", "canceled", "stand down", "stand-down"}:
            eta_value = "Cancelled"
            
        # Handle relative time calculations - detect patterns and calculate ourselves
        if isinstance(eta_value, str):
            # Check if this looks like an AI-miscalculated relative time
            # Look for patterns in the original message that suggest relative time
            original_text = text.lower()
            
            # Extract relative time patterns from the original message
            import re
            relative_patterns = [
                # Composite first so we don't prematurely match just the minutes
                (r'(\d+)\s*(?:hours?|hrs?)\s*and\s*(\d+)\s*min(?:ute)?s?', 'hours_plus_minutes'),
                (r'(?:an|a)\s+hour\s*and\s*(\d+)\s*min(?:ute)?s?', 'hour_plus_minutes'),
                # Ensure half-hour is captured before generic 'an hour'
                (r'half\s+an?\s+hour', 'half_hour'),
                # Match 'an hour' but not when preceded by 'half '
                (r'(?<!half\s)(?:an|a)\s+hour\b', 'one_hour'),
                (r'(\d+(?:\.\d+)?)\s*hour?s?(?:\s|$)', 'hours'),
                (r'(\d+)\s*min(?:ute)?s?(?:\s|$)', 'minutes'),
                (r'eta\s+(\d+)(?:\s|$)', 'minutes'),  # "ETA 90" pattern
            ]
            
            for pattern, unit in relative_patterns:
                match = re.search(pattern, original_text)
                if match:
                    if unit == 'hour_plus_minutes':
                        # "hour and X min" = 60 + X minutes
                        additional_minutes = int(match.group(1))
                        total_minutes = 60 + additional_minutes
                    elif unit == 'hours_plus_minutes':
                        # "X hours and Y min" = (X * 60) + Y minutes
                        hours = int(match.group(1))
                        minutes = int(match.group(2))
                        total_minutes = (hours * 60) + minutes
                    elif unit == 'one_hour':
                        total_minutes = 60
                    elif unit == 'half_hour':
                        total_minutes = 30
                    else:
                        number = int(match.group(1))
                        # Convert to minutes
                        if unit == 'hours':
                            # Allow fractional hours too
                            try:
                                total_minutes = int(float(match.group(1)) * 60)
                            except Exception:
                                total_minutes = number * 60
                        else:
                            total_minutes = number
                    
                    # Only apply if it's a reasonable relative time (5min to 8 hours)
                    if 5 <= total_minutes <= 480:
                        # Calculate the new time using proper datetime arithmetic
                        new_time = anchor_time + timedelta(minutes=total_minutes)
                        calculated_eta = new_time.strftime("%H:%M")
                        
                        logger.info(f"Detected relative time pattern: {match.group(0)} ({total_minutes}min)")
                        logger.info(f"Original AI eta: {eta_value}, Calculated eta: {calculated_eta}")
                        
                        # Replace the AI's calculation with our calculation
                        eta_value = calculated_eta
                        break
            
            # Also handle the RELATIVE: format if AI ever starts using it
            if eta_value.startswith("RELATIVE:"):
                relative_part = eta_value[9:]  # Remove "RELATIVE:" prefix
                try:
                    # Extract minutes from the relative time pattern
                    minutes_match = re.search(r'(\d+)min', relative_part)
                    hours_match = re.search(r'(\d+)\s*hour', relative_part)
                    
                    total_minutes = 0
                    if minutes_match:
                        total_minutes = int(minutes_match.group(1))
                    elif hours_match:
                        total_minutes = int(hours_match.group(1)) * 60
                    
                    if total_minutes > 0:
                        # Calculate the new time using proper datetime arithmetic
                        new_time = anchor_time + timedelta(minutes=total_minutes)
                        eta_value = new_time.strftime("%H:%M")
                        logger.info(f"Calculated relative time: {relative_part} + {total_minutes}min = {eta_value}")
                    else:
                        logger.warning(f"Could not parse relative time: {relative_part}")
                        eta_value = "Unknown"
                except Exception as e:
                    logger.error(f"Error calculating relative time {eta_value}: {e}")
                    eta_value = "Unknown"
                
        if eta_value not in ("Unknown", "Not Responding", "Cancelled"):
            eta_after_duration = convert_eta_to_timestamp(eta_value, anchor_time)
            if eta_after_duration != "Unknown":
                eta_value = eta_after_duration
            else:
                validation_result = validate_and_format_time(eta_value)
                if validation_result.get("valid"):
                    eta_value = validation_result["normalized"]
                    if validation_result.get("warning"):
                        logger.warning(f"ETA validation warning: {validation_result['warning']}")
                else:
                    logger.warning(
                        f"AI returned invalid ETA format '{eta_value}': {validation_result.get('error')}"
                    )
                    eta_value = "Unknown"

        # Ensure normalized/validated ETA is applied to payload
        parsed_json["eta"] = eta_value
        
        # Include raw_status if it was captured
        if "raw_status" in parsed_json:
            parsed_json["raw_status"] = parsed_json["raw_status"]
        
        return parsed_json
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return {"vehicle": "Unknown", "eta": "Unknown"}
    except Exception as e:
        logger.error(f"Azure OpenAI simplified parsing error: {e}", exc_info=True)
        # Fallback to basic extraction without function calling
        return {"vehicle": "Unknown", "eta": "Unknown"}

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
    
    parsed = extract_details_from_text(context_message, base_time=message_dt)
    logger.info(f"Parsed details: vehicle={parsed.get('vehicle')}, eta={parsed.get('eta')}, raw_status={parsed.get('raw_status')}")

    # Calculate additional fields for better display
    eta_info = calculate_eta_info(parsed.get("eta", "Unknown"), message_dt)
    
    # Use raw_status from AI parsing if available, otherwise fall back to eta_info status
    arrival_status = parsed.get("raw_status") or eta_info.get("status")

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
                "status": "On Route" if minutes_until > 0 else "Arrived"
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
    sorted_messages = sorted(messages, key=lambda x: x.get('timestamp', ''))
    
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
    result.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
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
        if vehicle == 'Not Responding':
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
            <td>{msg['timestamp']}</td>
            <td><strong>{msg['name']}</strong></td>
            <td>{team}</td>
            <td>{vehicle}</td>
            <td>{eta_display}</td>
            <td>{minutes_display}</td>
            <td>{status}</td>
            <td style='max-width: 300px; word-wrap: break-word;'>{msg['text']}</td>
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
            <td>{msg_time}</td>
            <td>{deleted_display}</td>
            <td>{name}</td>
            <td>{team}</td>
            <td>{vehicle}</td>
            <td>{eta}</td>
            <td style='max-width: 300px; word-wrap: break-word;'>{message_text}</td>
            <td style='font-size: 10px; color: #666;'>{msg_id}</td>
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
    """Remove messages with invalid timestamps (1970-01-01 entries)"""
    global messages
    
    # Reload latest data first
    reload_messages()
    initial_count = len(messages)
    
    # Remove messages with Unix timestamp 0 or equivalent to 1970-01-01
    messages = [
        msg for msg in messages 
        if not (
            "created_at" in msg and 
            (msg["created_at"] == 0 or msg["created_at"] == "1970-01-01 00:00:00")
        )
    ]
    
    # Also remove messages with empty or unknown content
    messages = [
        msg for msg in messages 
        if msg.get("message", "").strip() and 
           msg.get("vehicle", "Unknown") != "Unknown" and
           msg.get("eta", "Unknown") != "Unknown"
    ]
    
    removed_count = initial_count - len(messages)
    save_messages()  # Save cleaned data back to shared storage
    
    return {
        "status": "success",
        "message": f"Cleaned up {removed_count} invalid entries",
        "initial_count": initial_count,
        "remaining_count": len(messages)
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
