"""
Test FastAPI webhook security directly (bypassing OAuth2 proxy)
"""

import requests
import json
import os
from datetime import datetime

# Load environment variables
try:
    from dotenv import load_dotenv
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, '.env')
    load_dotenv(env_path)
except ImportError:
    pass

VALID_API_KEY = os.getenv('WEBHOOK_API_KEY')

def test_direct_webhook():
    """Test webhook security directly against FastAPI (port 8001)"""
    
    webhook_url = "http://localhost:8001/webhook"
    
    print(f"🔐 Testing FastAPI Webhook Security Directly")
    print("=" * 50)
    print(f"Endpoint: {webhook_url}")
    print()
    
    test_message = {
        "name": "Security Test",
        "text": "Testing direct FastAPI with SAR-1, ETA 15 minutes",
        "created_at": int(datetime.now().timestamp())
    }
    
    scenarios = [
        {
            "name": "Valid API Key",
            "headers": {'Content-Type': 'application/json', 'X-API-Key': VALID_API_KEY},
            "expected_status": 200
        },
        {
            "name": "No API Key",
            "headers": {'Content-Type': 'application/json'},
            "expected_status": 401
        },
        {
            "name": "Invalid API Key",
            "headers": {'Content-Type': 'application/json', 'X-API-Key': 'invalid-key'},
            "expected_status": 401
        }
    ]
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] Testing: {scenario['name']}")
        
        try:
            response = requests.post(webhook_url, json=test_message, headers=scenario['headers'], timeout=5)
            
            print(f"   Status: {response.status_code} (expected: {scenario['expected_status']})")
            
            if response.status_code == scenario['expected_status']:
                print(f"   Result: ✅ PASS")
            else:
                print(f"   Result: ❌ FAIL")
                
            if response.status_code != 200:
                try:
                    error_detail = response.json().get('detail', 'No detail')
                    print(f"   Error: {error_detail}")
                except:
                    print(f"   Response: {response.text[:100]}")
                    
        except requests.exceptions.RequestException as e:
            print(f"   Result: ❌ ERROR - {e}")
        
        print()

if __name__ == "__main__":
    test_direct_webhook()
