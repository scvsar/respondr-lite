"""
Send specific ETA test cases to preprod webhook and validate results
This tests the end-to-end functionality for the ETA 60min bug and related issues
"""

import json
import time
import requests
from datetime import datetime
from typing import Dict, Any

# Configuration for PREPROD
PREPROD_WEBHOOK_URL = "https://preprod.rtreit.com/webhook"
X_API_KEY = None  # Set if webhook requires authentication
GROUP_ID = "102193274"  # Test group
HEADERS = {"Content-Type": "application/json"}
if X_API_KEY:
    HEADERS["X-API-Key"] = X_API_KEY

def payload(name: str, text: str, created_at: int, group_id: str = GROUP_ID) -> Dict[str, Any]:
    """Build GroupMe-like payload"""
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

def to_epoch(ts_str: str) -> int:
    """Convert timestamp string to epoch seconds"""
    dt = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S")
    return int(time.mktime(dt.timetuple()))

# Specific test cases for ETA validation
ETA_TEST_CASES = [
    # The original bug case - should result in 13:39, not 01:00 AM
    ("08/11/2025 12:39:15", "Randy Treit", "Responding SAR7 ETA 60min"),
    
    # Other relative time cases that had issues
    ("08/11/2025 14:15:00", "Test User", "ETA 30 minutes"),
    ("08/11/2025 18:30:00", "Test User", "SAR-5 ETA 45min"),
    
    # Working cases for comparison
    ("08/11/2025 09:00:00", "Test User", "SAR-3 eta 8:30"),
    ("08/11/2025 09:00:00", "Test User", "POV ETA 0830"),
    
    # Cancellation cases
    ("08/11/2025 12:45:00", "Test User", "can't make it, sorry"),
    ("08/11/2025 12:46:00", "Test User", "10-22"),
]

def send_test_messages():
    """Send test messages to preprod webhook"""
    print("================================================================================")
    print("SENDING ETA TEST CASES TO PREPROD")
    print("================================================================================")
    print(f"Webhook URL: {PREPROD_WEBHOOK_URL}")
    print(f"Group ID: {GROUP_ID}")
    print("--------------------------------------------------------------------------------")
    
    success_count = 0
    total_count = len(ETA_TEST_CASES)
    
    for i, (timestamp, name, text) in enumerate(ETA_TEST_CASES, 1):
        print(f"\nTest {i}/{total_count}: Sending message")
        print(f"  Timestamp: {timestamp}")
        print(f"  Name: {name}")
        print(f"  Text: '{text}'")
        
        try:
            body = payload(name=name, text=text, created_at=to_epoch(timestamp))
            response = requests.post(PREPROD_WEBHOOK_URL, data=json.dumps(body), headers=HEADERS, timeout=30)
            
            print(f"  Response: {response.status_code}")
            if response.text:
                print(f"  Message: {response.text[:100]}...")
            
            if response.ok:
                success_count += 1
                print(f"  ✅ SUCCESS")
            else:
                print(f"  ❌ FAILED")
                
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
        
        # Small delay between requests
        time.sleep(1)
    
    print("\n" + "="*80)
    print(f"WEBHOOK TEST SUMMARY")
    print("="*80)
    print(f"Total messages sent: {total_count}")
    print(f"Successful: {success_count}")
    print(f"Failed: {total_count - success_count}")
    print(f"Success rate: {(success_count/total_count)*100:.1f}%")
    
    if success_count == total_count:
        print("\n✅ All webhook tests completed successfully!")
        print("\nNext steps:")
        print("1. Wait a few seconds for processing")
        print("2. Check Redis to see parsed results")
        print("3. Validate ETA calculations are correct")
    else:
        print(f"\n⚠️  {total_count - success_count} webhook tests failed")
        print("Check preprod logs for errors")
    
    return success_count == total_count

if __name__ == "__main__":
    send_test_messages()
