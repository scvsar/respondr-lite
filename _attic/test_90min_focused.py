"""
Focused test for the 90min ETA calculation bug
"""

import requests
import json
from datetime import datetime, timedelta

def test_90min_case():
    """Test the specific 90min case that was failing"""
    
    webhook_url = "http://localhost:8000/webhook"
    
    # Create precise timestamp
    timestamp = datetime.now()
    
    payload = {
        "name": "Test User 90min",
        "text": "Responding POV ETA 90min",
        "created_at": int(timestamp.timestamp()),
        "group_id": "test_90min_group",
        "user_id": "test_90min_user",
        "system": False
    }
    
    print("================================================================================")
    print("FOCUSED 90MIN ETA TEST")
    print("================================================================================")
    print(f"Sending at: {timestamp.strftime('%H:%M:%S')}")
    print(f"Message: '{payload['text']}'")
    print(f"Expected ETA: {(timestamp.replace(microsecond=0) + timedelta(minutes=90)).strftime('%H:%M')}")
    print("--------------------------------------------------------------------------------")
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        print(f"✅ Webhook Response: {response.status_code}")
        if response.status_code != 200:
            print(f"❌ Error: {response.text}")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Failed to send webhook: {e}")
        return False

if __name__ == "__main__":
    test_90min_case()
