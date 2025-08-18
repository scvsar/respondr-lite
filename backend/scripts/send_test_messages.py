#!/usr/bin/env python3
"""
Send realistic test messages with all three processing modes for comparison.
"""

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8000"

# Test messages with realistic responder names
TEST_MESSAGES = [
    {
        "name": "Mike Rodriguez", 
        "message": "Rolling out in SAR-74, ETA 15 minutes",
        "description": "Clear SAR unit response with specific ETA"
    },
    {
        "name": "Sarah Chen",
        "message": "Taking my POV, will be there in about an hour", 
        "description": "Personal vehicle with approximate time"
    }
]

MODES = [
    ("raw", "Raw (Rules-based)"),
    ("assisted", "Assisted (LLM spans + Rules)"), 
    ("llm-only", "LLM-Only (Pure AI)")
]

def send_message(name, message, mode):
    """Send a message with a specific processing mode."""
    url = f"{BASE_URL}/webhook"
    params = {"mode": mode}
    
    payload = {
        "name": name,
        "text": message  # Webhook expects "text" field, not "message"
    }
    
    try:
        response = requests.post(url, json=payload, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Error sending message: {e}")
        return None

def main():
    print("🧪 Sending Test Messages with All Processing Modes")
    print("=" * 60)
    
    # Check if backend is running
    try:
        response = requests.get(f"{BASE_URL}/api/responders", timeout=5)
        response.raise_for_status()
        print("✅ Backend is running")
    except Exception as e:
        print(f"❌ Backend not accessible: {e}")
        print("Please start the backend with: .\\dev-local.ps1")
        return
    
    for i, test_case in enumerate(TEST_MESSAGES, 1):
        print(f"\n🎯 Test Case {i}: {test_case['description']}")
        print(f"   Message: \"{test_case['message']}\"")
        print("-" * 40)
        
        for mode, mode_desc in MODES:
            # Add mode tag to name for easy identification
            tagged_name = f"{test_case['name']} [{mode_desc}]"
            
            print(f"📤 Sending as {mode} mode...")
            result = send_message(tagged_name, test_case['message'], mode)
            
            if result:
                print(f"✅ {mode_desc}: Processed successfully")
                # Show key extracted data
                if 'vehicle' in result:
                    print(f"   🚗 Vehicle: {result.get('vehicle', 'Unknown')}")
                if 'eta' in result:
                    print(f"   ⏰ ETA: {result.get('eta', 'Unknown')}")
                if 'status_source' in result:
                    print(f"   🔍 Source: {result.get('status_source', 'Unknown')}")
            else:
                print(f"❌ {mode_desc}: Failed to process")
            
            # Small delay between requests
            time.sleep(0.5)
    
    print(f"\n✅ All test messages sent!")
    print(f"🌐 View results at: {BASE_URL}")
    print("\nNow you can compare the different processing modes in the UI!")

if __name__ == "__main__":
    main()