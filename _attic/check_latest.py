#!/usr/bin/env python3
import redis
import json
from datetime import datetime

def check_latest_message():
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    data = r.get('respondr_messages')
    messages = json.loads(data) if data else []
    
    if messages:
        latest = messages[-1]
        print(f"Latest message:")
        print(f"  Text: '{latest.get('text', 'Unknown')}'")
        print(f"  Name: {latest.get('name', 'Unknown')}")
        print(f"  Vehicle: {latest.get('vehicle', 'Unknown')}")
        print(f"  ETA: {latest.get('eta', 'Unknown')}")
        print(f"  Status: {latest.get('status', 'Unknown')}")
        print()
        
        # Check if this is our 90min test
        if "ETA 90min" in latest.get('text', ''):
            print("🎯 This is our 90min test!")
            eta = latest.get('eta', 'Unknown')
            print(f"Current time was: 13:34")
            print(f"Expected ETA: ~15:04 (13:34 + 90min)")
            print(f"Actual ETA: {eta}")
            
            if eta == '15:04':
                print("✅ PERFECT! 90min calculation is working correctly!")
            elif eta == '14:04':
                print("❓ Close but 1 hour off - possible timezone issue")
            elif eta == '14:34':
                print("❓ Looks like only 60min added instead of 90min")
            else:
                print(f"❌ Unexpected ETA result")
    else:
        print("No messages found")

if __name__ == "__main__":
    check_latest_message()
