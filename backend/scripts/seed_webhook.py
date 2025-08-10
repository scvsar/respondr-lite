import json
import time
from datetime import datetime
from typing import Dict, Any
import requests

# Configuration
WEBHOOK_URL = "http://localhost:8000/webhook"
X_API_KEY = None  # Set to your WEBHOOK_API_KEY if required in your env
GROUP_ID = "102193274"  # OSU Test group by default; change if needed

# Helper to build GroupMe-like payload

def payload(name: str, text: str, created_at: int, group_id: str = GROUP_ID) -> Dict[str, Any]:
    return {
        "attachments": [],
        "avatar_url": "https://i.groupme.com/placeholder.jpeg",
        "created_at": created_at,
        "group_id": group_id,
        "id": str(created_at),
        "name": name,
        "sender_id": "000",
        "sender_type": "user",
        "source_guid": str(created_at),
        "system": False,
        "text": text,
        "user_id": "000",
    }

# Sample data (timestamp parsed as local time and converted to epoch seconds)
# Format: ("MM/DD/YYYY HH:MM:SS", name, text)
SAMPLES = [
    ("08/09/2025 14:30:14", "Seth Stone", "Have Hemroids, no go."),
    ("08/09/2025 14:30:05", "Randy Treit", "I don’t think I can make it, if I do it will be in an hour"),
    ("08/09/2025 14:29:25", "Randy Treit", "Can’t make it,!sorry"),
    ("08/09/2025 12:49:27", "Randy Treit", "Responding eta 32 min"),
    ("08/09/2025 12:48:48", "Randy Treit", "Responding pov eta 13:40"),
    ("08/09/2025 09:00:40", "Randy Treit", "Responding, should be there in a couple hours. Carpooling with John in SAR57"),
    ("08/09/2025 03:31:50", "Randy Treit", "Randy Responding POV, ETA 1 hour"),
    ("08/09/2025 03:19:02", "Seth Stone", "Responding pov arriving at 24:30hrs"),
    ("08/09/2025 03:16:49", "Seth Stone", "Responding in SAR12, ETA 57 hours."),
    ("08/09/2025 01:26:55", "Randy Treit", "Responding SAR56, ETA 1 hour"),
    ("08/09/2025 01:01:37", "Randy Treit", "Responding personal vehicle, should be on scene in 40 minutes"),
    ("08/09/2025 00:54:35", "Quinton Cline", "Responding pov eta 9:15"),
    ("08/08/2025 23:01:01", "Quinton Cline (OSU-4)", "Responding with SAR78 ETA 15 minutes"),
]

HEADERS = {"Content-Type": "application/json"}
if X_API_KEY:
    HEADERS["X-API-Key"] = X_API_KEY


def to_epoch(ts_str: str) -> int:
    # Assuming local time; adjust if needed
    dt = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S")
    # Treat naive as local time
    return int(time.mktime(dt.timetuple()))


def main():
    ok = 0
    for ts, name, text in SAMPLES:
        body = payload(name=name, text=text, created_at=to_epoch(ts))
        r = requests.post(WEBHOOK_URL, data=json.dumps(body), headers=HEADERS, timeout=10)
        print(ts, name, r.status_code, r.text)
        if r.ok:
            ok += 1
    print(f"Done. {ok}/{len(SAMPLES)} messages sent.")


if __name__ == "__main__":
    main()
