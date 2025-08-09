#!/usr/bin/env python3
"""
End-to-end test of the complete ETA parsing system
"""

import requests
import json
import time
import sys

def send_test_webhook(name, text, description):
    """Send a test webhook and display results"""
    print(f"\n🧪 Testing: {description}")
    print(f"📝 Input: '{text}'")
    
    webhook_data = {
        "name": name,
        "text": text,
        "created_at": int(time.time())
    }
    
    try:
        response = requests.post("http://localhost:8000/webhook", json=webhook_data, timeout=10)
        print(f"📤 Webhook Response: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Status: {result.get('status', 'unknown')}")
        else:
            print(f"❌ Error: {response.text}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")

def main():
    print("🚀 End-to-End ETA Parsing Test")
    print("=" * 50)
    print("Testing all the ETA parsing fixes in the live system")
    
    # Test 1: "ETA 9:15" should become "09:15" (zero-padded)
    send_test_webhook(
        "Alice Cooper", 
        "Responding with SAR-78, ETA 9:15",
        "ETA 9:15 → should display as 09:15 (zero-padded)"
    )
    
    time.sleep(2)  # Give processing time
    
    # Test 2: "24:30hrs" should become "00:30" (invalid time conversion)
    send_test_webhook(
        "Bob Wilson", 
        "I'll be arriving at 24:30hrs with SAR-12",
        "24:30hrs → should convert to 00:30 (next day)"
    )
    
    time.sleep(2)
    
    # Test 3: "57 hours" should be handled as unrealistic
    send_test_webhook(
        "Carol Davis", 
        "Taking my POV, ETA 57 hours from now",
        "57 hours → should be flagged as unrealistic"
    )
    
    time.sleep(2)
    
    # Test 4: Normal case for baseline
    send_test_webhook(
        "Dave Smith", 
        "Responding with SAR-45, ETA 15:30",
        "Normal ETA → should work unchanged"
    )
    
    time.sleep(2)
    
    # Test 5: Another edge case
    send_test_webhook(
        "Eve Johnson", 
        "ETA 7:05 with vehicle SAR-23",
        "ETA 7:05 → should display as 07:05"
    )
    
    print(f"\n🔍 View results at:")
    print(f"   Frontend: http://localhost:3100")
    print(f"   Backend Dashboard: http://localhost:8000/dashboard")
    print(f"   API: http://localhost:8000/api/responders")

if __name__ == "__main__":
    main()
