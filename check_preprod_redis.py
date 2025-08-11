"""
Check Redis in preprod to validate webhook test results
This validates that the ETA calculations are working correctly end-to-end
"""

import redis
import json
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv('backend/.env')

def connect_to_preprod_redis():
    """Connect to preprod Redis instance via port-forward"""
    # Connect to preprod Redis via kubectl port-forward on port 6380
    redis_host = 'localhost'
    redis_port = 6380  # Port-forwarded from preprod
    
    try:
        # Connect to preprod Redis via port-forward
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=True,
            socket_timeout=10
        )
        
        # Test connection
        r.ping()
        print(f"✅ Connected to preprod Redis via port-forward at {redis_host}:{redis_port}")
        return r
        
    except Exception as e:
        print(f"❌ Failed to connect to preprod Redis: {e}")
        print("\nNote: Make sure kubectl port-forward is running:")
        print("kubectl port-forward -n respondr-preprod svc/redis-service 6380:6379")
        return None

def get_test_messages(redis_client, group_id="102193274"):
    """Retrieve and analyze test messages from Redis"""
    if not redis_client:
        return
        
    print("================================================================================")
    print("REDIS PREPROD MESSAGE ANALYSIS")
    print("================================================================================")
    print(f"Group ID: {group_id}")
    print("--------------------------------------------------------------------------------")
    
    try:
        # Get all messages for the test group
        messages_key = f"messages:{group_id}"
        messages_json = redis_client.get(messages_key)
        
        if not messages_json:
            print(f"❌ No messages found for group {group_id}")
            return
            
        messages = json.loads(messages_json)
        print(f"📊 Found {len(messages)} total messages in group")
        
        # Filter for our recent test messages (last hour)
        current_time = datetime.now()
        test_messages = []
        
        for msg in messages:
            # Look for our test messages by name or recent timestamp
            if (msg.get('name') in ['Randy Treit', 'Test User'] or 
                'SAR7 ETA 60min' in msg.get('text', '') or
                'ETA 30 minutes' in msg.get('text', '') or
                'SAR-5 ETA 45min' in msg.get('text', '')):
                test_messages.append(msg)
        
        if not test_messages:
            print("❌ No test messages found")
            print("This could mean:")
            print("1. Messages are still being processed")
            print("2. Messages were filtered out")
            print("3. Wrong group ID or Redis connection")
            return
            
        print(f"🔍 Found {len(test_messages)} test messages")
        print("="*80)
        
        # Analyze each test message
        for i, msg in enumerate(test_messages, 1):
            print(f"\nMessage {i}: {msg.get('name', 'Unknown')}")
            print(f"  Text: '{msg.get('text', '')}'")
            print(f"  Vehicle: {msg.get('vehicle', 'Unknown')}")
            print(f"  ETA: {msg.get('eta', 'Unknown')}")
            print(f"  Raw Status: {msg.get('raw_status', 'N/A')}")
            print(f"  Arrival Status: {msg.get('arrival_status', 'Unknown')}")
            
            # Special validation for the original bug case
            if 'SAR7 ETA 60min' in msg.get('text', ''):
                eta = msg.get('eta', 'Unknown')
                print(f"  🎯 ORIGINAL BUG CASE:")
                if eta == "13:39":
                    print(f"     ✅ CORRECT - ETA is 13:39 (12:39 + 60min)")
                elif eta == "01:00":
                    print(f"     ❌ BUG STILL EXISTS - ETA is 01:00 AM (wrong!)")
                else:
                    print(f"     ⚠️  UNEXPECTED - ETA is {eta}")
            
            # Validate other cases
            text = msg.get('text', '')
            if 'ETA 30 minutes' in text:
                eta = msg.get('eta', 'Unknown')
                print(f"  📊 30min test: Expected ~14:45, got {eta}")
            elif 'SAR-5 ETA 45min' in text:
                eta = msg.get('eta', 'Unknown')
                print(f"  📊 45min test: Expected ~19:15, got {eta}")
            elif "can't make it" in text:
                status = msg.get('arrival_status', 'Unknown')
                print(f"  📊 Cancellation: Expected 'Cancelled', got '{status}'")
                
    except Exception as e:
        print(f"❌ Error retrieving messages: {e}")

def main():
    print("Connecting to preprod Redis to check webhook test results...")
    redis_client = connect_to_preprod_redis()
    
    if redis_client:
        get_test_messages(redis_client)
    else:
        print("\n💡 Alternative: Use the Redis sync script to copy preprod data locally:")
        print("   pwsh -File deployment/scripts/sync-redis-prod-to-preprod.ps1")
        print("   Then run this script against local Redis")

if __name__ == "__main__":
    main()
