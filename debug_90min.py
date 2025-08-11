"""
Debug script for the 90 minute ETA case
"""

import requests
import json
from datetime import datetime

def send_90min_test():
    """Send a specific test for the 90 minute case"""
    
    WEBHOOK_URL = "http://localhost:8000/webhook"
    
    timestamp = datetime.now()
    
    payload = {
        "name": "90min Test User",
        "text": "Responding POV ETA 90min",
        "created_at": int(timestamp.timestamp()),
        "group_id": "debug_90min",
        "user_id": "debug_user",
        "system": False
    }
    
    print("="*60)
    print("90 MINUTE ETA DEBUG TEST")
    print("="*60)
    print(f"Sending at: {timestamp.strftime('%H:%M:%S')}")
    print(f"Message: '{payload['text']}'")
    print(f"Expected ETA: {(timestamp.hour + 1):02d}:{(timestamp.minute + 30):02d} (90 minutes later)")
    
    try:
        response = requests.post(WEBHOOK_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        print(f"Response: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
            return False
        
        print("✅ Message sent successfully")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send: {e}")
        return False

if __name__ == "__main__":
    send_90min_test()
