import os
import json
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = FastAPI()
messages = []

client = OpenAI()

def extract_details_from_text(text: str) -> dict:
    try:
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

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        reply = response.choices[0].message.content.strip()
        return json.loads(reply)

    except Exception as e:
        print("OpenAI extraction error:", e)
        return {
            "vehicle": "Unknown",
            "eta": "Unknown"
        }

@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()

    name = data.get("name", "Unknown")
    text = data.get("text", "")
    created_at = data.get("created_at", 0)
    timestamp = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")

    parsed = extract_details_from_text(text)

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
