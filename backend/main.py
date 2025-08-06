import os
import sys
import json
import logging
import re
from datetime import datetime, timedelta

# Import fcntl only on Unix-like systems
try:
    import fcntl
except ImportError:
    fcntl = None
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

# Data storage file path
DATA_FILE = "/tmp/respondr_messages.json" if os.path.exists("/tmp") else "./respondr_messages.json"

# Load environment variables from .env file
load_dotenv()

# Validate environment variables
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")

# Webhook API key for security
webhook_api_key = os.getenv("WEBHOOK_API_KEY")

# Check if we're running in test mode
is_testing = os.getenv("PYTEST_CURRENT_TEST") is not None or "pytest" in sys.modules

if not is_testing and (not azure_openai_api_key or not azure_openai_endpoint or not azure_openai_deployment):
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

def load_messages():
    """Load messages from shared file"""
    global messages
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                messages = json.load(f)
            logger.info(f"Loaded {len(messages)} messages from shared storage")
        else:
            messages = []
            logger.info("No existing message file found, starting with empty list")
    except Exception as e:
        logger.error(f"Error loading messages: {e}")
        messages = []

def save_messages():
    """Save messages to shared file with file locking"""
    global messages
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        
        # Write with exclusive lock to prevent race conditions
        with open(DATA_FILE, 'w') as f:
            # Try to acquire exclusive lock (Unix-like systems)
            try:
                if fcntl:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                # Windows or systems without fcntl - proceed without locking
                pass
            json.dump(messages, f, indent=2)
        logger.debug(f"Saved {len(messages)} messages to shared storage")
    except Exception as e:
        logger.error(f"Error saving messages: {e}")

def reload_messages():
    """Reload messages from shared file to get latest data"""
    load_messages()

# Load messages on startup
load_messages()

# Initialize the Azure OpenAI client with credentials from .env
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

def extract_details_from_text(text: str) -> dict:
    try:
        logger.info(f"Extracting details from text: {text[:50]}...")
        
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
            import re
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
        return {
            "vehicle": "Unknown",
            "eta": "Unknown"
        }
    except Exception as e:
        logger.error(f"Azure OpenAI extraction error: {e}", exc_info=True)
        return {
            "vehicle": "Unknown",
            "eta": "Unknown"
        }

@app.post("/webhook")
async def receive_webhook(request: Request, api_key_valid: bool = Depends(validate_webhook_api_key)):
    data = await request.json()
    logger.info(f"Received webhook data from: {data.get('name', 'Unknown')}")

    name = data.get("name", "Unknown")
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

    parsed = extract_details_from_text(text)
    logger.info(f"Parsed details: vehicle={parsed.get('vehicle')}, eta={parsed.get('eta')}")

    # Calculate additional fields for better display
    eta_info = calculate_eta_info(parsed.get("eta", "Unknown"))

    message_record = {
        "name": name,
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

def calculate_eta_info(eta_str: str) -> dict:
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
            
            # Create full datetime for today
            eta_datetime = current_time.replace(
                hour=eta_time.hour, 
                minute=eta_time.minute, 
                second=0, 
                microsecond=0
            )
            
            # If ETA is earlier than current time, assume it's tomorrow
            if eta_datetime <= current_time:
                eta_datetime += timedelta(days=1)
            
            # Calculate minutes until arrival
            time_diff = eta_datetime - current_time
            minutes_until = int(time_diff.total_seconds() / 60)
            
            return {
                "eta_timestamp": eta_datetime.strftime("%Y-%m-%d %H:%M:%S"),
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

@app.get("/api/user")
def get_user_info(request: Request):
    """Get authenticated user information from OAuth2 Proxy headers"""
    # Debug: log all headers to see what OAuth2 proxy is sending
    print("=== DEBUG: All headers received ===")
    for header_name, header_value in request.headers.items():
        if header_name.lower().startswith('x-'):
            print(f"Header: {header_name} = {header_value}")
    print("=== END DEBUG ===")
    
    # OAuth2 Proxy with --set-xauthrequest=true sends X-Auth-Request-* headers
    # Check for the correct OAuth2 Proxy headers
    user_email = request.headers.get("X-Auth-Request-Email") or request.headers.get("X-Auth-Request-User")
    user_name = request.headers.get("X-Auth-Request-Preferred-Username") or request.headers.get("X-Auth-Request-User")
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
        authenticated = True
        display_name = user_name or user_email
        email = user_email
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
        "logout_url": "/oauth2/sign_out"  # OAuth2 Proxy logout endpoint
    })

@app.get("/debug/pod-info")
def get_pod_info():
    """Debug endpoint to show which pod is serving requests"""
    pod_name = os.getenv("HOSTNAME", "unknown-pod")
    pod_ip = os.getenv("POD_IP", "unknown-ip")
    return JSONResponse(content={
        "pod_name": pod_name,
        "pod_ip": pod_ip,
        "message_count": len(messages),
        "data_file_exists": os.path.exists(DATA_FILE)
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
