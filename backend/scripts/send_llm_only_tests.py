#!/usr/bin/env python3
"""
Send multiple test cases using LLM-only mode to explore its capabilities.
"""

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8000"

# Diverse test cases to explore LLM-only parsing capabilities
LLM_ONLY_TEST_CASES = [
    {
        "name": "Alex Martinez",
        "message": "En route in unit 42, ETA about 20 minutes",
        "description": "Clear unit number with approximate time"
    },
    {
        "name": "Jordan Kim", 
        "message": "Taking POV, stuck in traffic, maybe 45 min?",
        "description": "Uncertain ETA with question mark"
    },
    {
        "name": "Casey Johnson",
        "message": "Responding SAR-108, should be there by 11:30 PM",
        "description": "Absolute time with AM/PM"
    },
    {
        "name": "Riley Torres",
        "message": "Coming in my truck, probably an hour and a half",
        "description": "Personal vehicle with compound duration"
    },
    {
        "name": "Morgan Davis",
        "message": "Can't make it - working late tonight",
        "description": "Clear cancellation"
    },
    {
        "name": "Avery Wilson",
        "message": "Rolling out now, 30 mins max",
        "description": "Duration with qualifier 'max'"
    },
    {
        "name": "Cameron Brown",
        "message": "Taking SAR Rig, ETA 2145 hours",
        "description": "Military time format"
    },
    {
        "name": "Dakota Lee",
        "message": "Be there in a bit, maybe 15-20 minutes",
        "description": "Vague language with range"
    },
    {
        "name": "Sage Garcia",
        "message": "Available if you need backup",
        "description": "Available status, no immediate response"
    },
    {
        "name": "River Martinez",
        "message": "Just finished another call, heading your way in about 40",
        "description": "Context with duration, no unit specified"
    },
    {
        "name": "Finley Anderson",
        "message": "Sorry, equipment malfunction - can't respond",
        "description": "Unable to respond with reason"
    },
    {
        "name": "Emery Thompson",
        "message": "Responding in 99, ETA plus 10 from previous",
        "description": "Relative update (needs previous ETA context)"
    }
]

def send_llm_only_message(name, message):
    """Send a message using LLM-only mode."""
    url = f"{BASE_URL}/webhook"
    params = {"mode": "llm-only"}
    
    payload = {
        "name": name,
        "text": message  # Fixed: webhook expects 'text', not 'message'
    }
    
    try:
        print(f"    🔄 Sending to: {url}?mode=llm-only")
        print(f"    📦 Payload: {payload}")
        response = requests.post(url, json=payload, params=params, timeout=10)
        print(f"    📡 Response status: {response.status_code}")
        print(f"    📄 Response content: {response.text[:200]}...")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Error sending message: {e}")
        print(f"    Full error details: {type(e).__name__}: {str(e)}")
        return None

def main():
    print("🤖 LLM-Only Mode Test Suite")
    print("=" * 50)
    
    # Check if backend is running
    try:
        response = requests.get(f"{BASE_URL}/api/responders", timeout=5)
        response.raise_for_status()
        print("✅ Backend is running")
    except Exception as e:
        print(f"❌ Backend not accessible: {e}")
        print("Please ensure the backend is running")
        return
    
    print(f"\n🚀 Sending {len(LLM_ONLY_TEST_CASES)} LLM-only test cases...")
    print("-" * 50)
    
    successful = 0
    failed = 0
    
    for i, test_case in enumerate(LLM_ONLY_TEST_CASES, 1):
        print(f"\n{i:2d}. {test_case['name']}")
        print(f"    📝 {test_case['description']}")
        print(f"    💬 \"{test_case['message']}\"")
        
        # Send with [LLM-Only] tag for easy identification
        tagged_name = f"{test_case['name']} [LLM-Only]"
        result = send_llm_only_message(tagged_name, test_case['message'])
        
        if result:
            print(f"    ✅ Processed successfully")
            successful += 1
            
            # Show key results if available
            if 'vehicle' in result:
                print(f"       🚗 Vehicle: {result.get('vehicle', 'Unknown')}")
            if 'eta' in result:
                print(f"       ⏰ ETA: {result.get('eta', 'Unknown')}")
            if 'raw_status' in result:
                print(f"       📊 Status: {result.get('raw_status', 'Unknown')}")
            if 'status_source' in result:
                print(f"       🔍 Source: {result.get('status_source', 'Unknown')}")
        else:
            print(f"    ❌ Failed to process")
            failed += 1
        
        # Small delay between requests to be kind to the API
        time.sleep(0.3)
    
    print(f"\n📊 Results Summary:")
    print(f"   ✅ Successful: {successful}")
    print(f"   ❌ Failed: {failed}")
    print(f"   📝 Total: {len(LLM_ONLY_TEST_CASES)}")
    
    print(f"\n🌐 View results at: {BASE_URL}/dashboard")
    print("🔍 Look for entries tagged with '[LLM-Only]' to see how the AI handled each case!")

if __name__ == "__main__":
    main()