"""
Check local Redis for webhook test results
This will examine how the ETA messages were processed
"""

import redis
import json
from datetime import datetime

def check_local_redis():
    """Check local Redis for processed webhook messages"""
    
    try:
        # Connect to local Redis (default Docker Compose setup)
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        
        print("================================================================================")
        print("LOCAL REDIS ANALYSIS")
        print("================================================================================")
        print(f"Analysis started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Check what keys exist
        print("Available Redis keys:")
        keys = r.keys('*')
        for key in keys:
            print(f"  - {key}")
        print()
        
        # Look for message data
        message_keys = [key for key in keys if 'messages' in key.lower() or 'group' in key.lower()]
        
        if not message_keys:
            print("❌ No message-related keys found in Redis")
            print("   This might mean:")
            print("   1. Messages haven't been processed yet")
            print("   2. Redis key naming is different")
            print("   3. Local instance isn't running")
            return
        
        print(f"Found {len(message_keys)} message-related keys:")
        
        for key in message_keys:
            print(f"\n--- Key: {key} ---")
            
            # Try to get the data
            try:
                data = r.get(key)
                if data:
                    # Try to parse as JSON
                    try:
                        parsed_data = json.loads(data)
                        if isinstance(parsed_data, list):
                            print(f"  Found {len(parsed_data)} messages")
                            
                            # Look for our test messages
                            test_messages = []
                            for msg in parsed_data:
                                if isinstance(msg, dict):
                                    text = msg.get('text', '')
                                    name = msg.get('name', '')
                                    eta = msg.get('eta', 'Unknown')
                                    vehicle = msg.get('vehicle', 'Unknown')
                                    
                                    # Check if this is one of our test messages
                                    if ('ETA' in text and 'min' in text) or 'Can\'t make it' in text:
                                        test_messages.append({
                                            'text': text,
                                            'name': name,
                                            'eta': eta,
                                            'vehicle': vehicle,
                                            'raw_msg': msg
                                        })
                            
                            if test_messages:
                                print(f"  🎯 Found {len(test_messages)} test messages:")
                                for i, test_msg in enumerate(test_messages, 1):
                                    print(f"    {i}. '{test_msg['text']}'")
                                    print(f"       Name: {test_msg['name']}")
                                    print(f"       Vehicle: {test_msg['vehicle']}")
                                    print(f"       ETA: {test_msg['eta']}")
                                    
                                    # Check for the specific bug case
                                    if 'SAR7 ETA 60min' in test_msg['text']:
                                        print(f"       🔍 ORIGINAL BUG TEST CASE:")
                                        print(f"           ETA should be current_time + 60min")
                                        print(f"           ETA should NOT be 01:00 AM")
                                        if test_msg['eta'] == '01:00':
                                            print(f"           ❌ BUG REPRODUCED: Got 01:00 AM!")
                                        else:
                                            print(f"           ✅ Bug appears fixed: Got {test_msg['eta']}")
                                    print()
                            else:
                                print("  No test messages found in this key")
                        else:
                            print(f"  Data type: {type(parsed_data)}")
                            print(f"  Content preview: {str(parsed_data)[:200]}...")
                    except json.JSONDecodeError:
                        print(f"  Raw data (not JSON): {data[:200]}...")
                else:
                    print(f"  No data found for key {key}")
            except Exception as e:
                print(f"  Error reading key {key}: {e}")
    
    except redis.ConnectionError:
        print("❌ Cannot connect to local Redis")
        print("   Make sure Redis is running (docker-compose up)")
        print("   Expected: localhost:6379")
    except Exception as e:
        print(f"❌ Error checking Redis: {e}")

if __name__ == "__main__":
    check_local_redis()
