#!/usr/bin/env python3
"""
Live test script to verify ETA parsing fixes in the running application
"""
import requests
import json
import time

def test_eta_parsing():
    """Test the ETA parsing fixes with the live application"""
    
    # Test cases that were problematic before
    test_cases = [
        {
            "name": "Test User 1",
            "text": "I am responding with SAR-78, ETA 9:15",
            "expected_eta": "09:15",
            "issue": "Missing zero padding"
        },
        {
            "name": "Test User 2", 
            "text": "Taking my POV, arriving at 24:30hrs",
            "expected_eta": "00:30",
            "issue": "Invalid 24:30 time"
        },
        {
            "name": "Test User 3",
            "text": "Responding with SAR-12, ETA 57 hours",
            "expected_behavior": "Should cap at reasonable time",
            "issue": "Unrealistic duration"
        }
    ]
    
    print("🧪 Testing ETA Parsing Fixes")
    print("=" * 50)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. Testing: {test_case['issue']}")
        print(f"   Input: '{test_case['text']}'")
        
        webhook_data = {
            "name": test_case["name"],
            "text": test_case["text"],
            "created_at": int(time.time())
        }
        
        try:
            # Send webhook
            response = requests.post("http://localhost:8000/webhook", json=webhook_data)
            
            if response.status_code == 200:
                print(f"   ✅ Webhook accepted")
                
                # Get responder data
                responders = requests.get("http://localhost:8000/api/responders")
                if responders.status_code == 200:
                    data = responders.json()
                    # Find our test user
                    user_data = next((r for r in data if r["name"] == test_case["name"]), None)
                    if user_data:
                        print(f"   📊 Result:")
                        print(f"      Vehicle: {user_data['vehicle']}")
                        print(f"      ETA: {user_data['eta']}")
                        print(f"      ETA Timestamp: {user_data['eta_timestamp']}")
                        
                        if "expected_eta" in test_case:
                            if user_data["eta"] == test_case["expected_eta"]:
                                print(f"   ✅ ETA matches expected: {test_case['expected_eta']}")
                            else:
                                print(f"   ❌ ETA mismatch. Expected: {test_case['expected_eta']}, Got: {user_data['eta']}")
                    else:
                        print(f"   ❌ Could not find user data for {test_case['name']}")
                else:
                    print(f"   ❌ Failed to get responders: {responders.status_code}")
            else:
                print(f"   ❌ Webhook failed: {response.status_code}")
                print(f"   Response: {response.text}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print(f"\n🌐 View results at: http://localhost:3100")
    print(f"📋 Dashboard: http://localhost:8000/dashboard")

if __name__ == "__main__":
    test_eta_parsing()
