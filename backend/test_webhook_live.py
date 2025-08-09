#!/usr/bin/env python3
"""
Simple webhook test for the live environment
"""
import requests
import time
import json

def test_webhook():
    """Test webhook with ETA parsing cases"""
    
    test_cases = [
        {
            "name": "Zero Padding Test",
            "text": "Responding with SAR-100, ETA 9:15",
            "expected": "09:15"
        },
        {
            "name": "24:30 Test", 
            "text": "Taking my POV, arriving at 24:30hrs",
            "expected": "00:30"
        }
    ]
    
    print("🧪 Live Webhook Testing")
    print("=" * 40)
    
    for test in test_cases:
        print(f"\n🔹 {test['name']}")
        print(f"   Input: {test['text']}")
        
        webhook_data = {
            "name": test["name"],
            "text": test["text"],
            "created_at": int(time.time())
        }
        
        try:
            # Wait for server to be ready
            for i in range(5):
                try:
                    response = requests.post("http://localhost:8000/webhook", 
                                           json=webhook_data, timeout=5)
                    break
                except requests.exceptions.ConnectionError:
                    if i == 4:
                        raise
                    print(f"   Waiting for server... ({i+1}/5)")
                    time.sleep(2)
            
            if response.status_code == 200:
                print(f"   ✅ Webhook accepted")
                
                # Get results
                time.sleep(1)  # Brief delay
                responders = requests.get("http://localhost:8000/api/responders")
                if responders.status_code == 200:
                    data = responders.json()
                    # Find our test
                    result = next((r for r in data if r["name"] == test["name"]), None)
                    if result:
                        eta = result["eta"]
                        print(f"   📊 ETA Result: '{eta}'")
                        if eta == test["expected"]:
                            print(f"   ✅ PASS - Expected '{test['expected']}', got '{eta}'")
                        else:
                            print(f"   ❌ FAIL - Expected '{test['expected']}', got '{eta}'")
                        print(f"   📋 Status: {result['arrival_status']}")
                    else:
                        print(f"   ❌ Could not find test result")
                else:
                    print(f"   ❌ Failed to get responders: {responders.status_code}")
            else:
                print(f"   ❌ Webhook failed: {response.status_code}")
                print(f"   Response: {response.text}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print(f"\n🌐 View results at:")
    print(f"   Frontend: http://localhost:3100")
    print(f"   Dashboard: http://localhost:8000/dashboard")

if __name__ == "__main__":
    test_webhook()
