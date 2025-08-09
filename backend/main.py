import os
import sys
import json
import logging
import re
from typing import Any, Dict, cast
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import importlib
import redis
from contextlib import asynccontextmanager
from pathlib import Path
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

# Check if we're running in test mode
is_testing = os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules

# temporarily disable api-key check in test mode
disable_api_key_check = True

def is_email_domain_allowed(email: str) -> bool:
    """Check if the user's email domain is in the allowed domains list"""
    if not email:
        return False
    
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

from contextlib import asynccontextmanager


app = FastAPI(
    title="Respondr API",
    description="API for tracking responder information",
    version="1.0.0",
    lifespan=lifespan,
)

messages = []

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
            redis_client.ping()
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
        if messages is None:
            messages = []
        logger.debug(f"Test mode: Using in-memory storage with {len(messages)} messages")
        return
        
    try:
        init_redis()
        if redis_client:
            data = redis_client.get(REDIS_KEY)
            if data:
                messages = json.loads(data)
                logger.info(f"Loaded {len(messages)} messages from Redis")
            else:
                messages = []
                logger.info("No existing messages in Redis, starting with empty list")
        else:
            messages = []
            logger.warning("Redis not available, using empty message list")
    except Exception as e:
        logger.error(f"Error loading messages from Redis: {e}")
        messages = []

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
            logger.warning("Redis not available, cannot save messages")
    except Exception as e:
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
    client = AzureOpenAI(
        api_key=azure_openai_api_key,
        azure_endpoint=azure_openai_endpoint,
        api_version=azure_openai_api_version,
    )

def convert_eta_to_timestamp(eta_str: str, current_time: datetime) -> str:
    """Convert ETA string to HH:MM format, handling duration calculations"""
    try:
        # If already in HH:MM format, return as-is
        if re.match(r'^\d{1,2}:\d{2}$', eta_str):
            return eta_str

        # Convert to lowercase for easier matching
        eta_lower = eta_str.lower()

        # Extract numbers from the string
        numbers = re.findall(r'\d+', eta_str)

        # Handle duration patterns
        if any(word in eta_lower for word in ['min', 'minute']):
            if numbers:
                minutes = int(numbers[0])
                result_time = current_time + timedelta(minutes=minutes)
                return result_time.strftime('%H:%M')

        elif any(word in eta_lower for word in ['hour', 'hr']):
            if numbers:
                hours = int(numbers[0])
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

                if period == 'pm' and hour != 12:
                    hour += 12
                elif period == 'am' and hour == 12:
                    hour = 0

                return f"{hour:02d}:{minute:02d}"

        # If we can't parse it, return the original
        logger.warning(f"Could not parse ETA: {eta_str}")
        return eta_str

    except Exception as e:
        logger.warning(f"Error converting ETA '{eta_str}': {e}")
        return eta_str

def extract_details_from_text(text: str) -> Dict[str, str]:
    try:
        logger.info(f"Extracting details from text: {text[:50]}...")

        # Fast-path: lightweight heuristic parser for local/dev seeding
        if FAST_LOCAL_PARSE:
            tl = text.lower()
            # Not responding / off-topic signals
            if any(k in tl for k in ["can't make it", "cannot make it", "not coming", "won't make", "family emergency", "off topic", "weather up there", "just checking"]):
                return {"vehicle": "Not Responding", "eta": "Not Responding"}

            # Vehicle detection
            vehicle = "Unknown"
            m = re.search(r"\bsar\s*-?\s*(\d{1,3})\b", tl)
            if m:
                vehicle = f"SAR-{m.group(1)}"
            elif any(k in tl for k in ["pov", "personal vehicle", "own car", "driving myself", "my car"]):
                vehicle = "POV"
            elif "sar rig" in tl:
                vehicle = "SAR Rig"

            # ETA detection (duration or explicit time)
            eta = "Unknown"
            # HH:MM (12h with am/pm or 24h)
            m_time = re.search(r"\b(\d{1,2}:\d{2}\s*(am|pm)?)\b", tl)
            # durations
            m_min = re.search(r"\b(\d{1,2})\s*(min|mins|minutes)\b", tl)
            m_hr = re.search(r"\b(\d{1,2})\s*(hour|hr|hours|hrs)\b", tl)
            half_hr = "half" in tl and ("hour" in tl or "hr" in tl)

            # Use local time for consistency with server-side calculations
            current_time = datetime.now()
            if m_time:
                eta = convert_eta_to_timestamp(m_time.group(1), current_time)
            elif m_min:
                eta = convert_eta_to_timestamp(f"{m_min.group(1)} minutes", current_time)
            elif m_hr:
                eta = convert_eta_to_timestamp(f"{m_hr.group(1)} hour", current_time)
            elif half_hr:
                eta = convert_eta_to_timestamp("half hour", current_time)

            return {"vehicle": vehicle, "eta": eta}

        # Get current time for ETA calculations
        current_time = datetime.now()
        current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
        current_time_short = current_time.strftime("%H:%M")

        prompt = (
            "You are an expert at extracting responder information from SAR (Search and Rescue) messages.\n"
            "Extract vehicle assignment and ETA from the following message.\n\n"
            f"CURRENT TIME: {current_time_str} (24-hour format: {current_time_short})\n\n"
            "VEHICLE RULES:\n"
            "- If using a SAR vehicle (e.g., SAR78, SAR rig, SAR-4, SAR12), return the vehicle identifier exactly as mentioned\n"
            "- If using personal vehicle (POV, personal car, own car, driving myself), return 'POV'\n"
            "- If vehicle is not mentioned or unclear, return 'Unknown'\n\n"
            "ETA RULES - MUST ALWAYS CALCULATE ACTUAL TIME:\n"
            "Convert ALL ETAs to 24-hour time format (HH:MM) by calculating the actual arrival time:\n\n"
            "FOR DURATIONS - Add to current time and return calculated time:\n"
            f"- Current time is {current_time_short}\n"
            "- '5 minutes' → return calculated time (current + 5 min)\n"
            "- '15 minutes' → return calculated time (current + 15 min)\n"
            "- '30 minutes' → return calculated time (current + 30 min)\n"
            "- 'half hour' → return calculated time (current + 30 min)\n"
            "- '1 hour' → return calculated time (current + 60 min)\n"
            "- '20 mins' → return calculated time (current + 20 min)\n"
            "- 'about 25 minutes out' → return calculated time (current + 25 min)\n\n"
            "FOR CLOCK TIMES - Convert to 24-hour format:\n"
            "- '11:45 PM' → '23:45'\n"
            "- '10:30 AM' → '10:30'\n"
            "- '22:45' → '22:45' (already correct)\n"
            "- '23:30' → '23:30' (already correct)\n\n"
            "EXAMPLES:\n"
            f"- 'ETA 15 minutes' → calculate {current_time_short} + 15 min and return result\n"
            "- 'will be there by 23:30' → return '23:30'\n"
            f"- 'about 2 hours out' → calculate {current_time_short} + 2 hours and return result\n\n"
            "NEVER return duration text like '5min', '15 minutes', 'half an hour' - always calculate actual time!\n"
            "If ETA is not mentioned or unclear, return 'Unknown'\n\n"
            "IMPORTANT: If the message is not about responding to an incident (e.g., casual chat, off-topic), "
            "return {\"vehicle\": \"Not Responding\", \"eta\": \"Not Responding\"}\n\n"
            "Sender name context may include nicknames or team tags in parentheses. Ignore sender name content when determining vehicle/ETA."
            " Only use the message text itself to infer vehicle and ETA.\n\n"
            "Return ONLY valid JSON in this exact format:\n"
            "{\"vehicle\": \"value\", \"eta\": \"HH:MM\"}\n\n"
            f"Message: \"{text}\"\n\n"
            "JSON Response:"
        )

        logger.info(f"Calling Azure OpenAI with deployment: {azure_openai_deployment}")

        # Prepare the messages in the format expected by Azure OpenAI
        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]

    # Call the Azure OpenAI API with the correct parameters
    if client is None:
            raise RuntimeError("Azure client not initialized")
        response = client.chat.completions.create(
            model=azure_openai_deployment,
            messages=messages,
            temperature=0,
            max_tokens=1000,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0,
            stop=None
        )

        reply = response.choices[0].message.content

        # Try to clean up the response if it has extra text
        reply = reply.strip()

        # Look for JSON content in the response
        if reply.startswith('{') and reply.endswith('}'):
            parsed_json = json.loads(reply)
        else:
            # Try to extract JSON from response that might have extra text
            json_match = re.search(r'\{[^}]+\}', reply)
            if json_match:
                parsed_json = json.loads(json_match.group())
            else:
                logger.warning(f"No valid JSON found in response: '{reply}'")
                raise ValueError(f"Invalid response format: {reply}")

        # Validate the required fields exist
        if 'vehicle' not in parsed_json or 'eta' not in parsed_json:
            logger.warning(f"Missing required fields in response: {parsed_json}")
            raise ValueError(f"Missing required fields: {parsed_json}")

        # Post-process ETA to ensure it's in HH:MM format
        eta_value = parsed_json['eta']
        if eta_value not in ["Unknown", "Not Responding"]:
            eta_value = convert_eta_to_timestamp(eta_value, current_time)
            parsed_json['eta'] = eta_value

        return parsed_json

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error with response '{reply}': {e}")
        return {"vehicle": "Unknown", "eta": "Unknown"}
    except Exception as e:
        logger.error(f"Azure OpenAI extraction error: {e}", exc_info=True)
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
    
    # Handle invalid or missing timestamps
    try:
        if created_at == 0 or created_at is None:
            # Use current time if timestamp is missing or invalid
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.warning(f"Missing or invalid timestamp for message from {name}, using current time")
        else:
            timestamp = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError) as e:
        # Handle invalid timestamp values
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
    parsed = extract_details_from_text(f"Sender: {display_name}. Message: {text}")
    logger.info(f"Parsed details: vehicle={parsed.get('vehicle')}, eta={parsed.get('eta')}")

    # Calculate additional fields for better display
    eta_info = calculate_eta_info(parsed.get("eta", "Unknown"))

    message_record = {
    "name": display_name,
        "text": text,
        "timestamp": timestamp,
        "vehicle": parsed.get("vehicle", "Unknown"),
        "eta": parsed.get("eta", "Unknown"),
        "eta_timestamp": eta_info.get("eta_timestamp"),
        "minutes_until_arrival": eta_info.get("minutes_until_arrival"),
        "arrival_status": eta_info.get("status")
    }

    # Reload messages to get latest data from other pods
    reload_messages()
    messages.append(message_record)
    save_messages()  # Save to shared storage
    return {"status": "ok"}

def calculate_eta_info(eta_str: str) -> Dict[str, Any]:
    """Calculate additional ETA information for better display"""
    try:
        if eta_str in ["Unknown", "Not Responding"]:
            return {
                "eta_timestamp": None,
                "minutes_until_arrival": None,
                "status": eta_str
            }
        
        # Try to parse as HH:MM format
        if ":" in eta_str and len(eta_str) == 5:  # HH:MM format
            current_time = datetime.now()
            eta_time = datetime.strptime(eta_str, "%H:%M")
            # Apply to today's date
            eta_datetime = current_time.replace(
                hour=eta_time.hour,
                minute=eta_time.minute,
                second=0,
                microsecond=0
            )
            # If ETA is earlier/equal than current time, assume it's later today (or next day if needed)
            if eta_datetime <= current_time:
                eta_datetime += timedelta(days=1)
            time_diff = eta_datetime - current_time
            minutes_until = int(time_diff.total_seconds() / 60)
            
            return {
                # Return ISO-like string (local) for reliable JS parsing
                "eta_timestamp": eta_datetime.strftime("%Y-%m-%dT%H:%M:%S"),
                "minutes_until_arrival": minutes_until,
                "status": "On Route" if minutes_until > 0 else "Arrived"
            }
        else:
            # Fallback for non-standard formats
            return {
                "eta_timestamp": None,
                "minutes_until_arrival": None,
                "status": "ETA Format Unknown"
            }
            
    except Exception as e:
        logger.warning(f"Error calculating ETA info for '{eta_str}': {e}")
        return {
            "eta_timestamp": None,
            "minutes_until_arrival": None,
            "status": "ETA Parse Error"
        }

@app.get("/api/responders")
def get_responder_data():
    reload_messages()  # Get latest data from shared storage
    return JSONResponse(content=messages)

@app.post("/api/clear-all")
def clear_all_data(request: Request):
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
    return {"status": "cleared", "removed": initial}

@app.get("/api/user")
def get_user_info(request: Request):
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
            redis_client.ping()
            redis_status = "connected"
    except:
        redis_status = "error"
    
    return JSONResponse(content={
        "pod_name": pod_name,
        "pod_ip": pod_ip,
        "message_count": len(messages),
        "redis_status": redis_status
    })

@app.get("/dashboard", response_class=HTMLResponse)
def display_dashboard():
    current_time = datetime.now()
    
    html = f"""
    <h1>🚨 Responder Dashboard</h1>
    <p><strong>Current Time:</strong> {current_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <table border='1' cellpadding='8' style='border-collapse: collapse; font-family: monospace;'>
        <tr style='background-color: #f0f0f0;'>
            <th>Message Time</th>
            <th>Name</th>
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
def cleanup_invalid_timestamps(api_key: str = Depends(validate_webhook_api_key)):
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
