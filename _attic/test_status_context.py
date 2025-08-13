#!/usr/bin/env python3

import requests
import json
import time
from datetime import datetime

def send_message(name, text, user_id="randy_test_123", group_id="context_test"):
    """Send a message to the webhook"""
    payload = {
        'name': name,
        'text': text,
        'created_at': int(datetime.now().timestamp()),
        'group_id': group_id,
        'user_id': user_id,
        'system': False
    }
    
    response = requests.post('http://localhost:8000/webhook', json=payload)
    print(f"Sent: '{text}' -> Status: {response.status_code}")
    return response.status_code == 200

def get_current_status():
    """Get current status from the API"""
    response = requests.get('http://localhost:8000/api/current-status')
    if response.status_code == 200:
        return response.json()
    return []

def test_context_aware_status():
    """Test the context-aware status logic"""
    
    print("🧪 Testing Context-Aware Status Logic")
    print("=" * 50)
    
    # Test 1: Initial responding message
    print("\n1️⃣ Sending initial responding message...")
    send_message("Randy Treit", "Responding SAR7 ETA 60min")
    time.sleep(2)
    
    status = get_current_status()
    randy_status = next((s for s in status if s['name'] == 'Randy Treit'), None)
    
    if randy_status:
        print(f"✅ Initial Status: {randy_status['arrival_status']} | ETA: {randy_status.get('eta', 'None')}")
    else:
        print("❌ No status found for Randy Treit")
        return
    
    # Test 2: ETA update from already responding user
    print("\n2️⃣ Sending ETA update message...")
    send_message("Randy Treit", "Actually I'll be an hour and 10 min")
    time.sleep(2)
    
    status = get_current_status()
    randy_status = next((s for s in status if s['name'] == 'Randy Treit'), None)
    
    if randy_status:
        print(f"✅ Updated Status: {randy_status['arrival_status']} | ETA: {randy_status.get('eta', 'None')}")
        
        if randy_status['arrival_status'] == 'Responding':
            print("🎉 SUCCESS: Status correctly remained 'Responding' for ETA update!")
        else:
            print(f"❌ FAILED: Status changed to '{randy_status['arrival_status']}' instead of staying 'Responding'")
    else:
        print("❌ No status found for Randy Treit after update")
    
    # Show full messages for debugging
    print("\n📋 Full API Response:")
    response = requests.get('http://localhost:8000/api/responders')
    if response.status_code == 200:
        messages = response.json()
        randy_messages = [m for m in messages if m['name'] == 'Randy Treit']
        
        for i, msg in enumerate(randy_messages[-2:], 1):  # Show last 2 messages
            print(f"  Message {i}:")
            print(f"    Text: {msg['text']}")
            print(f"    Status: {msg['arrival_status']}")
            print(f"    ETA: {msg.get('eta', 'None')}")
            print(f"    Vehicle: {msg.get('vehicle', 'Unknown')}")
            print()

if __name__ == "__main__":
    test_context_aware_status()
