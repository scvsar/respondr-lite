"""
Test script to send webhook messages to local dev instance
This will test the ETA calculation scenarios we've been working on
"""

import requests
import json
from datetime import datetime, timedelta
import time

# Local webhook endpoint
WEBHOOK_URL = "http://localhost:8000/webhook"

def send_webhook_message(text, sender_name, group_id="test_group_123", team="TestTeam"):
    """Send a webhook message to local instance"""
    
    # Create timestamp for the message
    timestamp = datetime.now()
    
    # Use GroupMe webhook format
    payload = {
        "name": sender_name,
        "text": text,
        "created_at": int(timestamp.timestamp()),
        "group_id": group_id,
        "user_id": f"user_{hash(sender_name) % 10000}",
        "system": False
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(WEBHOOK_URL, json=payload, headers=headers, timeout=10)
        print(f"✅ Sent: '{text}' from {sender_name}")
        print(f"   Response: {response.status_code}")
        if response.status_code != 200:
            print(f"   Error: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Failed to send '{text}': {e}")
        return False

def test_eta_scenarios():
    """Test the specific ETA scenarios we've been investigating"""
    
    print("================================================================================")
    print("LOCAL WEBHOOK ETA TESTING")
    print("================================================================================")
    print(f"Sending test messages to: {WEBHOOK_URL}")
    print(f"Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Test cases - focusing on the ETA scenarios
    test_cases = [
        # The original bug case
        {
            "text": "Responding SAR7 ETA 60min",
            "sender": "Randy Treit",
            "description": "Original bug case - should be current_time + 60min, NOT 01:00 AM"
        },
        
        # Other relative time scenarios
        {
            "text": "SAR-3 ETA 30min", 
            "sender": "Test User 1",
            "description": "30 minute relative ETA"
        },
        
        {
            "text": "ETA 45 minutes",
            "sender": "Test User 2", 
            "description": "Generic ETA with minutes"
        },
        
        {
            "text": "Responding POV ETA 90min",
            "sender": "Test User 3",
            "description": "90 minute relative ETA"
        },
        
        # Absolute time scenarios for comparison
        {
            "text": "SAR-5 ETA 15:30",
            "sender": "Test User 4",
            "description": "Absolute time ETA"
        },
        
        # Cancellation for comparison
        {
            "text": "Can't make it, sorry",
            "sender": "Test User 5",
            "description": "Cancellation message"
        }
    ]
    
    successful_sends = 0
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test {i}/{len(test_cases)}: {test_case['description']}")
        print(f"Message: '{test_case['text']}'")
        
        success = send_webhook_message(
            text=test_case['text'],
            sender_name=test_case['sender'],
            group_id=f"eta_test_group_{i}",
            team="ETA_Testing"
        )
        
        if success:
            successful_sends += 1
            
        print()
        time.sleep(1)  # Small delay between sends
    
    print("="*80)
    print(f"WEBHOOK SENDING COMPLETE")
    print(f"Successfully sent: {successful_sends}/{len(test_cases)} messages")
    print(f"Test completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print("Next steps:")
    print("1. Check local Redis to see how messages were processed")
    print("2. Check local logs for any parsing errors")
    print("3. Compare expected vs actual ETA calculations")

if __name__ == "__main__":
    test_eta_scenarios()
