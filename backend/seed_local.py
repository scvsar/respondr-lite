# Minimal local seeder: posts a few GroupMe-like payloads to the local webhook
# Uses only stdlib (urllib) so no extra dependencies required.

import json
import time
from datetime import datetime, timedelta
from urllib import request as urlrequest

WEBHOOK = "http://localhost:8000/webhook"
RESPONDERS = "http://localhost:8000/api/responders"

messages = [
    ("John Smith", "Responding with SAR78 ETA 15 minutes", 6),
    ("Sarah Johnson", "Taking POV, should be there by 23:30", 5),
    ("Mike Rodriguez", "I will take SAR-4, ETA 20 mins", 4),
    ("Lisa Chen", "Responding in my personal vehicle, about 25 minutes out", 3),
    ("Grace Lee", "Hey team, just checking the weather up there", 2),
]

def post_json(url: str, payload: dict) -> int:
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlrequest.urlopen(req, timeout=15) as resp:
        return resp.status


def get_json(url: str):
    with urlrequest.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def make_payload(name: str, text: str, mins_ago: int) -> dict:
    created_at = int((datetime.utcnow() - timedelta(minutes=mins_ago)).timestamp())
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    return {
        "attachments": [],
        "avatar_url": "https://i.groupme.com/1024x1024.jpeg.placeholder",
        "created_at": created_at,
        "group_id": "123456789",
        "id": str(now_ms),
        "name": name,
        "sender_id": "30001234",
        "sender_type": "user",
        "source_guid": f"{now_ms:016X}",
        "system": False,
        "text": text,
        "user_id": "30001234",
    }


def main():
    sent = 0
    for name, text, mins in messages:
        try:
            status = post_json(WEBHOOK, make_payload(name, text, mins))
            print(f"POST [{name}] -> {status}")
            sent += 1
            time.sleep(0.2)
        except Exception as e:
            print(f"POST [{name}] ERROR: {e}")
    try:
        data = get_json(RESPONDERS)
        print(f"Responders count: {len(data)}")
        if data:
            # print first 1-2 for sanity
            preview = data[:2]
            print(json.dumps(preview, indent=2))
    except Exception as e:
        print(f"GET /api/responders ERROR: {e}")


if __name__ == "__main__":
    main()
