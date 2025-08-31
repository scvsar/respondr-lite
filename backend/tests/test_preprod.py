#!/usr/bin/env python3
"""
Test script for preprod environment

This script provides easy testing against the preprod.rtreit.com endpoint.
"""

import requests
import time
import argparse
import os
from typing import Dict, Any
from datetime import datetime

# Load environment variables
try:
    from dotenv import load_dotenv
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, '.env')
    
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"Loaded environment from: {env_path}")
    else:
        load_dotenv()
        print("Loaded environment from default locations")
except ImportError:
    print("python-dotenv not installed, using system environment variables only")

WEBHOOK_API_KEY = os.getenv('WEBHOOK_API_KEY')

def get_preprod_webhook_url() -> str:
    """Get the preprod webhook URL"""
    return "https://preprod.rtreit.com/webhook"

def get_preprod_api_url() -> str:
    """Get the preprod API URL"""  
    return "https://preprod.rtreit.com/api/responders"

def create_test_message(name: str, text: str) -> Dict[str, Any]:
    """Create a simple test message for preprod"""
    return {
        "id": str(int(datetime.now().timestamp() * 1000000)),
        "name": name,
        "text": text,
        "created_at": int(datetime.now().timestamp()),
        "group_id": "12345678",
        "sender_id": "87654321",
        "user_id": "87654321",
        "sender_type": "user",
        "source_guid": "test-guid",
        "system": False,
        "attachments": [],
        "avatar_url": "https://i.groupme.com/placeholder.jpeg"
    }

def send_test_message(name: str, text: str) -> bool:
    """Send a test message to preprod webhook"""
    webhook_url = get_preprod_webhook_url()
    message = create_test_message(name, text)
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    if WEBHOOK_API_KEY:
        headers['X-API-Key'] = WEBHOOK_API_KEY
    else:
        print("⚠️  Warning: No API key available")
    
    try:
        response = requests.post(webhook_url, json=message, headers=headers, timeout=10)
        if response.status_code == 200:
            print(f"✅ Sent: {name}: '{text}'")
            return True
        else:
            print(f"❌ Failed: {response.status_code} - {name}: '{text}'")
            if response.text:
                print(f"   Response: {response.text[:100]}")
            return False
    except requests.exceptions.Timeout:
        print(f"⏱️  Timeout: {name}: '{text}'")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"🔌 Connection Error: {name}: '{text}' - {str(e)[:100]}")
        return False
    except Exception as e:
        print(f"❌ Error: {name}: '{text}' - {str(e)[:100]}")
        return False

def test_preprod_basic():
    """Run basic preprod tests"""
    print("🧪 Testing preprod environment: https://preprod.rtreit.com")
    print("="*60)
    
    test_messages = [
        ("John Smith", "Change Unit to Team - Testing preprod deployment"),
        ("Jane Doe", "Responding with SAR-1, ETA 15 minutes"),
        ("Mike Johnson", "Taking POV, will be there in 20"),
        ("Test User", "Can't make it tonight")
    ]
    
    successful = 0
    for name, text in test_messages:
        if send_test_message(name, text):
            successful += 1
        time.sleep(1)  # Small delay between messages
    
    print(f"\n📊 Results: {successful}/{len(test_messages)} messages sent successfully")
    print(f"\n🌐 Manual verification:")
    print(f"   1. Visit: https://preprod.rtreit.com")
    print(f"   2. Sign in with Azure AD")
    print(f"   3. Verify messages appear in the dashboard")
    print(f"   4. Check that 'Unit' column now shows 'Team'")

def main():
    parser = argparse.ArgumentParser(description="Test preprod environment")
    parser.add_argument("--name", help="Your name for test message")
    parser.add_argument("--message", help="Test message to send")
    
    args = parser.parse_args()
    
    if args.name and args.message:
        # Send single custom message
        print(f"Sending custom message to preprod...")
        send_test_message(args.name, args.message)
    else:
        # Run basic test suite
        test_preprod_basic()

if __name__ == "__main__":
    main()
