import os
import sys
import json
import logging
import re
from typing import Any, Dict, Optional, cast
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
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from openai import AzureOpenAI

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

# GroupMe group_id to Team mapping
# Source: provided GroupMe group list
GROUP_ID_TO_TEAM: Dict[str, str] = {
    "102193274": "OSUTest",
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

# Initialize Redis client
redis_client = None

# Only require Azure configuration if not in fast local parse mode
if not is_testing and not FAST_LOCAL_PARSE and (not azure_openai_api_key or not azure_openai_endpoint or not azure_openai_deployment):
    logger.error("Missing required Azure OpenAI configuration")
    raise ValueError("AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, and AZURE_OPENAI_DEPLOYMENT must be set in the .env file")
elif is_testing:
    logger.info("Running in test mode - using mock Azure OpenAI configuration")
    # Set default test values if not provided
    azure_openai_api_key = azure_openai_api_key or "test-key"
    azure_openai_endpoint = azure_openai_endpoint or "https://test-endpoint.openai.azure.com/"
    azure_openai_deployment = azure_openai_deployment or "test-deployment"
    azure_openai_api_version = azure_openai_api_version or "2025-01-01-preview"
    webhook_api_key = webhook_api_key or "test-webhook-key"

if not is_testing and not webhook_api_key:
    logger.error("Missing WEBHOOK_API_KEY environment variable")
    raise ValueError("WEBHOOK_API_KEY must be set for webhook authentication")


def validate_webhook_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    """Validate the API key for webhook endpoint"""
    if is_testing:
        return True  # Skip validation in tests
    
    if disable_api_key_check:
        return True

    if not x_api_key or x_api_key != webhook_api_key:
        logger.warning(f"Invalid or missing API key for webhook request")
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include 'X-API-Key' header.",
            headers={"WWW-Authenticate": "API-Key"}
        )
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager"""
    # Startup
    logger.info("Starting Respondr API application")
    logger.info(f"Using Azure OpenAI API at: {azure_openai_endpoint}")
    logger.info(f"Using deployment: {azure_openai_deployment}")
    yield
    # Shutdown
    logger.info("Shutting down Respondr API application")

app = FastAPI(
    title="Respondr API",
    description="API for tracking responder information",
    version="1.0.0",
    lifespan=lifespan,
)

messages: list[Dict[str, Any]] = []

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
            # Parse and validate the time
            hour, minute = map(int, eta_str.split(':'))
            
            # Handle invalid times like 24:30
            if hour > 23:
                if hour == 24 and minute == 0:
                    return "00:00"  # 24:00 -> 00:00 next day
                elif hour == 24 and minute <= 59:
                    return f"00:{minute:02d}"  # 24:30 -> 00:30 next day
                else:
                    logger.warning(f"Invalid hour {hour} in ETA '{eta_str}', returning Unknown")
                    return "Unknown"
            
            if minute > 59:
                logger.warning(f"Invalid minute {minute} in ETA '{eta_str}', returning Unknown")
                return "Unknown"
            
            # Return properly formatted time (zero-padded)
            return f"{hour:02d}:{minute:02d}"

        # Convert to lowercase for easier matching
        eta_lower = eta_str.lower()

        # Extract numbers from the string
        numbers = re.findall(r'\d+', eta_str)

        # Handle duration patterns
        if any(word in eta_lower for word in ['min', 'minute']):
            if numbers:
                minutes = int(numbers[0])
                # Cap at reasonable maximum (24 hours)
                if minutes > 1440:
                    logger.warning(f"ETA of {minutes} minutes is unrealistic, capping at 24 hours")
                    minutes = 1440
                result_time = current_time + timedelta(minutes=minutes)
                return result_time.strftime('%H:%M')

        elif any(word in eta_lower for word in ['hour', 'hr']):
            if numbers:
                hours = int(numbers[0])
                # Cap at reasonable maximum
                if hours > 24:
                    logger.warning(f"ETA of {hours} hours is unrealistic, capping at 24 hours")
                    hours = 24
                result_time = current_time + timedelta(hours=hours)
                return result_time.strftime('%H:%M')

        elif 'half' in eta_lower and any(word in eta_lower for word in ['hour', 'hr']):
            result_time = current_time + timedelta(minutes=30)
            return result_time.strftime('%H:%M')

        # Handle AM/PM formats
        elif any(period in eta_lower for period in ['am', 'pm']):
            # Extract time part
            time_match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)', eta_lower)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                period = time_match.group(3)

                # Validate minute
                if minute > 59:
                    logger.warning(f"Invalid minute {minute} in ETA '{eta_str}'")
                    return "Unknown"

                if period == 'pm' and hour != 12:
                    hour += 12
                elif period == 'am' and hour == 12:
                    hour = 0

                return f"{hour:02d}:{minute:02d}"
            
            # Handle cases like "9am" or "10pm" (no minutes)
            hour_match = re.search(r'(\d{1,2})\s*(am|pm)', eta_lower)
            if hour_match:
                hour = int(hour_match.group(1))
                period = hour_match.group(2)
                
                if period == 'pm' and hour != 12:
                    hour += 12
                elif period == 'am' and hour == 12:
                    hour = 0
                
                return f"{hour:02d}:00"

        # Handle 24-hour format without colon (e.g., "0915", "2430")
        if re.match(r'^\d{3,4}$', eta_str):
            if len(eta_str) == 3:
                # e.g., "915" -> "09:15"
                hour = int(eta_str[0])
                minute = int(eta_str[1:3])
            else:
                # e.g., "0915" or "2430"
                hour = int(eta_str[:2])
                minute = int(eta_str[2:4])
            
            # Validate and handle edge cases
            if hour > 23:
                if hour == 24 and minute <= 59:
                    return f"00:{minute:02d}"  # 24xx -> 00:xx next day
                else:
                    logger.warning(f"Invalid hour {hour} in ETA '{eta_str}'")
                    return "Unknown"
            
            if minute > 59:
                logger.warning(f"Invalid minute {minute} in ETA '{eta_str}'")
                return "Unknown"
            
            return f"{hour:02d}:{minute:02d}"

        # If we can't parse it, return Unknown instead of original
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
        # Not responding / off-topic signals
        if any(k in tl for k in ["can't make it", "cannot make it", "not coming", "won't make", "family emergency", "off topic", "weather up there", "just checking"]):
            return {"vehicle": "Not Responding", "eta": "Not Responding"}

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
        m_min = re.search(r"\b(\d{1,2})\s*(min|mins|minutes)\b", tl)
        m_hr = re.search(r"\b(\d{1,2})\s*(hour|hr|hours|hrs)\b", tl)
        half_hr = "half" in tl and ("hour" in tl or "hr" in tl)

        # Use the message's timestamp (if provided via base_time) to anchor duration math
        current_time = anchor_time
        if m_time:
            eta = convert_eta_to_timestamp(m_time.group(1), current_time)
        elif m_min:
            eta = convert_eta_to_timestamp(f"{m_min.group(1)} minutes", current_time)
        elif m_hr:
            eta = convert_eta_to_timestamp(f"{m_hr.group(1)} hour", current_time)
        elif half_hr:
            eta = convert_eta_to_timestamp("half hour", current_time)

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
            "CRITICAL: First check if the message indicates the person CANNOT or WILL NOT respond:\n"
            "- Messages like \"can't make it\", \"cannot make it\", \"won't make it\", \"not coming\", \"family emergency\", \"sorry\"\n"
            "- For ANY declining/negative response, return: {\"vehicle\": \"Not Responding\", \"eta\": \"Not Responding\"}\n\n"
            "For responding messages:\n"
            "- Vehicle: Extract SAR identifier (e.g., 'SAR-12') or return 'POV' for personal vehicle or 'Unknown'\n"
            "- ETA: Convert to 24-hour format (HH:MM) or 'Unknown'\n"
            "- For durations like '30 minutes', add to current time\n"
            "- For times like '9:15 PM', convert to 24-hour format (21:15)\n\n"
            f"MESSAGE: \"{text}\"\n\n"
            "Return ONLY this JSON format: "
            '{\"vehicle\": \"value\", \"eta\": \"HH:MM|Unknown|Not Responding\"}'
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

        if "vehicle" not in parsed_json or "eta" not in parsed_json:
            logger.warning(f"Missing required fields in response: {parsed_json}")
            return {"vehicle": "Unknown", "eta": "Unknown"}

        # Apply additional validation to the AI's result
        eta_value = parsed_json.get("eta", "Unknown")
        if eta_value not in ("Unknown", "Not Responding"):
            # Validate the AI's ETA result
            validation_result = validate_and_format_time(eta_value)
            if validation_result.get("valid"):
                eta_value = validation_result["normalized"]
                if validation_result.get("warning"):
                    logger.warning(f"ETA validation warning: {validation_result['warning']}")
            else:
                logger.warning(f"AI returned invalid ETA format '{eta_value}': {validation_result.get('error')}")
                eta_value = "Unknown"

        # Ensure normalized/validated ETA is applied to payload
        parsed_json["eta"] = eta_value
        
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

    # Provide sender context to AI while instructing it (in the prompt) to ignore names for vehicle/ETA
    parsed = extract_details_from_text(f"Sender: {display_name}. Message: {text}", base_time=message_dt)
    logger.info(f"Parsed details: vehicle={parsed.get('vehicle')}, eta={parsed.get('eta')}")

    # Calculate additional fields for better display
    eta_info = calculate_eta_info(parsed.get("eta", "Unknown"), message_dt)

    message_record: Dict[str, Any] = {
        "name": display_name,
        "text": text,
        "timestamp": timestamp,
        "timestamp_utc": message_dt.astimezone(timezone.utc).isoformat() if message_dt else None,
        "group_id": group_id or None,
        "team": team,
        "vehicle": parsed.get("vehicle", "Unknown"),
        "eta": parsed.get("eta", "Unknown"),
        "eta_timestamp": eta_info.get("eta_timestamp"),
        "eta_timestamp_utc": eta_info.get("eta_timestamp_utc"),
        "minutes_until_arrival": eta_info.get("minutes_until_arrival"),
        "arrival_status": eta_info.get("status")
    }

    # Reload messages to get latest data from other pods
    reload_messages()
    messages.append(message_record)
    save_messages()  # Save to shared storage
    return {"status": "ok"}

def calculate_eta_info(eta_str: str, message_time: Optional[datetime] = None) -> Dict[str, Any]:
    """Calculate additional ETA information for better display"""
    try:
        if eta_str in ["Unknown", "Not Responding"]:
            return {
                "eta_timestamp": None,
                "eta_timestamp_utc": None,
                "minutes_until_arrival": None,
                "status": eta_str
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
        if ALLOW_LOCAL_AUTH_BYPASS:
            # Local dev: pretend there's a logged-in user
            authenticated = True
            display_name = os.getenv("LOCAL_DEV_USER_NAME", "Local Dev")
            email = os.getenv("LOCAL_DEV_USER_EMAIL", "dev@local.test")
        else:
            authenticated = False
            display_name = None
            email = None
    
    return JSONResponse(content={
        "authenticated": authenticated,
        "email": email,
        "name": display_name,
        "groups": [group.strip() for group in user_groups if group.strip()],
        # Redirect to root after logout so OAuth2 Proxy can initiate a new login
        "logout_url": f"/oauth2/sign_out?rd={quote('/', safe='')}",
    })

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
    current_time = datetime.now()
    
    html = f"""
    <h1>🚨 Responder Dashboard</h1>
    <p><strong>Current Time:</strong> {current_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
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
