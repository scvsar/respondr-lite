import os
import json
import logging
import re
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
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

# Validate environment variables
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")


if not azure_openai_api_key or not azure_openai_endpoint or not azure_openai_deployment:
    logger.error("Missing required Azure OpenAI configuration")
    raise ValueError("AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, and AZURE_OPENAI_DEPLOYMENT must be set in the .env file")

app = FastAPI(
    title="Respondr API",
    description="API for tracking responder information",
    version="1.0.0",
)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Respondr API application")
    logger.info(f"Using Azure OpenAI API at: {azure_openai_endpoint}")
    logger.info(f"Using deployment: {azure_openai_deployment}")

messages = []

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
async def receive_webhook(request: Request):
    data = await request.json()
    logger.info(f"Received webhook data from: {data.get('name', 'Unknown')}")

    name = data.get("name", "Unknown")
    text = data.get("text", "")
    created_at = data.get("created_at", 0)
    timestamp = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")

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

    messages.append(message_record)
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
    return JSONResponse(content=messages)

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

app.mount("/static", StaticFiles(directory=os.path.join(frontend_build, "static")), name="static")

@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(frontend_build, "index.html"))
