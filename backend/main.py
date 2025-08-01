import os
import json
import logging
from datetime import datetime
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

logger.info(f"Azure OpenAI Endpoint: {azure_openai_endpoint}")
logger.info(f"Azure OpenAI Deployment: {azure_openai_deployment}")
logger.info(f"Azure OpenAI API Version: {azure_openai_api_version}")

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

def extract_details_from_text(text: str) -> dict:
    try:
        logger.info(f"Extracting details from text: {text[:50]}...")
        
        prompt = (
            "Extract responder information from the following message.\n"
            "- If the responder is taking a SAR vehicle (e.g., SAR78, SAR rig, SAR-4), return the vehicle as-is (e.g., 'SAR78').\n"
            "- If they are using a personal vehicle, return 'POV'.\n"
            "- Also extract ETA, either as a clock time like '23:50' or duration like '30 minutes'.\n"
            "Return only valid JSON in this format:\n"
            "{ \"vehicle\": \"SAR78\", \"eta\": \"23:50\" }\n"
            "If anything is missing or unclear, use 'Unknown'.\n\n"
            f"Message: \"{text}\"\n\n"
            "Output:"
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
        logger.info(f"Received response: {reply}")
        return json.loads(reply)

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

    message_record = {
        "name": name,
        "text": text,
        "timestamp": timestamp,
        "vehicle": parsed.get("vehicle", "Unknown"),
        "eta": parsed.get("eta", "Unknown")
    }

    messages.append(message_record)
    return {"status": "ok"}

@app.get("/api/responders")
def get_responder_data():
    return JSONResponse(content=messages)

@app.get("/dashboard", response_class=HTMLResponse)
def display_dashboard():
    html = "<h1>Responder Dashboard</h1><table border='1' cellpadding='8'><tr><th>Time</th><th>Name</th><th>Message</th><th>Vehicle</th><th>ETA</th></tr>"
    for msg in reversed(messages):
        html += f"<tr><td>{msg['timestamp']}</td><td>{msg['name']}</td><td>{msg['text']}</td><td>{msg['vehicle']}</td><td>{msg['eta']}</td></tr>"
    html += "</table>"
    return html

frontend_build = os.path.join(os.path.dirname(__file__), "../frontend/build")
app.mount("/static", StaticFiles(directory=os.path.join(frontend_build, "static")), name="static")

@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(frontend_build, "index.html"))
