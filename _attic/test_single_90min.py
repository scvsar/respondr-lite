#!/usr/bin/env python3
"""
Single 90min ETA test to verify our fix is working
"""
import requests
import json
from datetime import datetime

def test_single_90min():
    webhook_url = "http://localhost:8000/webhook"
    
    # GroupMe webhook format
    test_payload = {
        "created_at": int(datetime.now().timestamp()),
        "group_id": "test-group",
        "id": "test-message-id",
        "name": "90min Test User",
        "sender_id": "test-sender",
        "sender_type": "user",
        "source_guid": "test-guid",
        "text": "Responding POV ETA 90min",
        "user_id": "test-user"
    }
    
    print("================================================================================")
    print("SINGLE 90MIN ETA TEST")
    print("================================================================================")
    print(f"Current time: {datetime.now().strftime('%H:%M:%S')}")
    print(f"Message: '{test_payload['text']}'")
    print(f"Expected ETA: Current time + 90 minutes")
    print()
    
    response = requests.post(webhook_url, json=test_payload)
    print(f"✅ Response: {response.status_code}")
    
    if response.status_code == 200:
        print("✅ Webhook processed successfully")
        print("\nNow check Redis to see the result...")
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    test_single_90min()
