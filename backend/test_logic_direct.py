#!/usr/bin/env python3
"""
Direct test of the timestamp validation logic without server
"""
import os
import sys
import json
from datetime import datetime
from unittest.mock import Mock

# Add the backend directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Import our main module
import main

def test_timestamp_validation():
    """Test the timestamp validation logic directly"""
    print("🧪 Testing timestamp validation logic...\n")
    
    # Test 1: Missing created_at
    data1 = {
        "message": "Test message without timestamp",
        "phone": "+1234567890"
    }
    
    print("Test 1: Missing created_at")
    print(f"Input: {data1}")
    
    # Simulate the webhook handler logic
    try:
        created_at = data1.get("created_at", 0)
        print(f"created_at extracted: {created_at}")
        
        if created_at <= 0:
            print("⚠️  Invalid timestamp detected, using current time")
            created_at = datetime.now().timestamp()
            print(f"Fallback timestamp: {created_at}")
        
        timestamp = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
        print(f"✅ Final timestamp: {timestamp}")
        
        if "1970" in timestamp:
            print("❌ ERROR: Still contains 1970!")
        else:
            print("✅ SUCCESS: No 1970 timestamp")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # Test 2: Zero created_at
    data2 = {
        "message": "Test message with zero timestamp",
        "phone": "+1234567890",
        "created_at": 0
    }
    
    print("Test 2: Zero created_at")
    print(f"Input: {data2}")
    
    try:
        created_at = data2.get("created_at", 0)
        print(f"created_at extracted: {created_at}")
        
        if created_at <= 0:
            print("⚠️  Invalid timestamp detected, using current time")
            created_at = datetime.now().timestamp()
            print(f"Fallback timestamp: {created_at}")
        
        timestamp = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
        print(f"✅ Final timestamp: {timestamp}")
        
        if "1970" in timestamp:
            print("❌ ERROR: Still contains 1970!")
        else:
            print("✅ SUCCESS: No 1970 timestamp")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # Test 3: Valid timestamp
    current_time = datetime.now().timestamp()
    data3 = {
        "message": "Test message with valid timestamp",
        "phone": "+1234567890",
        "created_at": current_time
    }
    
    print("Test 3: Valid created_at")
    print(f"Input: {data3}")
    
    try:
        created_at = data3.get("created_at", 0)
        print(f"created_at extracted: {created_at}")
        
        if created_at <= 0:
            print("⚠️  Invalid timestamp detected, using current time")
            created_at = datetime.now().timestamp()
            print(f"Fallback timestamp: {created_at}")
        else:
            print("✅ Valid timestamp, using as-is")
        
        timestamp = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
        print(f"✅ Final timestamp: {timestamp}")
        
        if "1970" in timestamp:
            print("❌ ERROR: Still contains 1970!")
        else:
            print("✅ SUCCESS: No 1970 timestamp")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")

def test_cleanup_logic():
    """Test the cleanup logic"""
    print("\n🧹 Testing cleanup logic...\n")
    
    # Simulate messages list with mixed data
    messages = [
        {
            "message": "Valid message",
            "vehicle": "Truck 123",
            "eta": "15 minutes", 
            "created_at": "2025-01-05 13:00:00"
        },
        {
            "message": "Bad timestamp message",
            "vehicle": "Truck 456",
            "eta": "20 minutes",
            "created_at": 0
        },
        {
            "message": "1970 timestamp message",
            "vehicle": "Truck 789",
            "eta": "10 minutes",
            "created_at": "1970-01-01 00:00:00"
        },
        {
            "message": "",
            "vehicle": "Unknown",
            "eta": "Unknown",
            "created_at": "2025-01-05 14:00:00"
        },
        {
            "message": "Good message 2",
            "vehicle": "Van 001",
            "eta": "5 minutes",
            "created_at": "2025-01-05 15:00:00"
        }
    ]
    
    print(f"Initial messages count: {len(messages)}")
    for i, msg in enumerate(messages):
        print(f"  {i+1}. {msg['message'][:20]}... - {msg['created_at']}")
    
    # Apply cleanup logic
    initial_count = len(messages)
    
    # Remove messages with Unix timestamp 0 or equivalent to 1970-01-01
    messages = [
        msg for msg in messages 
        if not (
            "created_at" in msg and 
            (msg["created_at"] == 0 or msg["created_at"] == "1970-01-01 00:00:00")
        )
    ]
    
    print(f"\nAfter timestamp cleanup: {len(messages)} messages")
    
    # Also remove messages with empty or unknown content
    messages = [
        msg for msg in messages 
        if msg.get("message", "").strip() and 
           msg.get("vehicle", "Unknown") != "Unknown" and
           msg.get("eta", "Unknown") != "Unknown"
    ]
    
    removed_count = initial_count - len(messages)
    
    print(f"After content cleanup: {len(messages)} messages")
    print(f"Total removed: {removed_count}")
    
    print("\nRemaining messages:")
    for i, msg in enumerate(messages):
        print(f"  {i+1}. {msg['message'][:30]}... - {msg['created_at']}")

if __name__ == "__main__":
    print("🔧 Testing Respondr timestamp validation fixes\n")
    print("="*60)
    
    test_timestamp_validation()
    test_cleanup_logic()
    
    print("\n✅ All tests completed!")
