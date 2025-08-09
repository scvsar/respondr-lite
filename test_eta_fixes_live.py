#!/usr/bin/env python3
"""
Live test of ETA parsing fixes
Tests the specific cases that were reported as bugs
"""

import requests
import json
import time

def test_webhook(name, text, description):
    """Send a webhook and print the result"""
    print(f"\n🧪 Testing: {description}")
    print(f"📝 Input: '{text}'")
    
    webhook_data = {
        "name": name,
        "text": text,
        "created_at": int(time.time())
    }
    
    try:
        # Send webhook
        response = requests.post("http://localhost:8000/webhook", json=webhook_data, timeout=30)
        print(f"📤 Webhook Status: {response.status_code}")
        
        if response.status_code == 200:
            # Get the responder data to see how it was parsed
            time.sleep(1)  # Give it a moment to process
            responders = requests.get("http://localhost:8000/api/responders", timeout=10)
            
            if responders.status_code == 200:
                data = responders.json()
                # Find our message (it should be the most recent)
                for responder in data:
                    if responder.get("name") == name and text in responder.get("text", ""):
                        print(f"✅ Vehicle: {responder.get('vehicle', 'N/A')}")
                        print(f"✅ ETA: {responder.get('eta', 'N/A')}")
                        print(f"✅ ETA Timestamp: {responder.get('eta_timestamp', 'N/A')}")
                        break
                else:
                    print("⚠️  Message not found in responder data")
            else:
                print(f"❌ Failed to get responder data: {responders.status_code}")
        else:
            print(f"❌ Webhook failed: {response.text}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    print("🚀 Testing ETA Parsing Fixes - Live Environment")
    print("=" * 50)
    
    # Test Case 1: "ETA 9:15" (should become "09:15")
    test_webhook(
        "Alice Test", 
        "I'm responding with SAR-78, ETA 9:15",
        "ETA 9:15 should become 09:15 (zero-padded)"
    )
    
    # Test Case 2: "ETA 57 hours" (should be capped or calculated reasonably)
    test_webhook(
        "Bob Test", 
        "Taking my POV, ETA 57 hours from now",
        "ETA 57 hours should be handled realistically"
    )
    
    # Test Case 3: "arriving at 24:30hrs" (should become "00:30")
    test_webhook(
        "Carol Test", 
        "I'll be arriving at 24:30hrs with SAR-12",
        "arriving at 24:30hrs should become 00:30"
    )
    
    # Test Case 4: Normal case for comparison
    test_webhook(
        "Dave Test",
        "Responding with SAR-45, ETA 15:30",
        "Normal ETA format (should work unchanged)"
    )
    
    print(f"\n🔍 Check the dashboard at: http://localhost:8000/dashboard")
    print(f"🔍 Check the frontend at: http://localhost:3100")

if __name__ == "__main__":
    main()
