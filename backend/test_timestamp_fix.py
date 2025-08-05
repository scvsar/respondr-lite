#!/usr/bin/env python3
"""
Test the timestamp validation fixes
"""
import os
import sys
import requests
import json
from datetime import datetime

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Get webhook API key
WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY")
if not WEBHOOK_API_KEY:
    print("❌ WEBHOOK_API_KEY not found in environment")
    sys.exit(1)

BASE_URL = "http://localhost:8000"

def test_webhook_with_invalid_timestamp():
    """Test webhook with missing or invalid timestamp"""
    headers = {"X-API-Key": WEBHOOK_API_KEY, "Content-Type": "application/json"}
    
    # Test 1: Missing created_at
    payload1 = {
        "message": "Test message without timestamp",
        "phone": "+1234567890"
    }
    
    print("🧪 Testing webhook with missing created_at...")
    response = requests.post(f"{BASE_URL}/webhook", 
                           headers=headers, 
                           json=payload1)
    
    print(f"Response status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    # Test 2: Invalid created_at (0)
    payload2 = {
        "message": "Test message with zero timestamp",
        "phone": "+1234567890",
        "created_at": 0
    }
    
    print("\n🧪 Testing webhook with created_at = 0...")
    response = requests.post(f"{BASE_URL}/webhook", 
                           headers=headers, 
                           json=payload2)
    
    print(f"Response status: {response.status_code}")
    print(f"Response: {response.json()}")

def test_cleanup_endpoint():
    """Test the cleanup endpoint"""
    headers = {"X-API-Key": WEBHOOK_API_KEY}
    
    print("\n🧹 Testing cleanup endpoint...")
    response = requests.post(f"{BASE_URL}/cleanup/invalid-timestamps", 
                           headers=headers)
    
    print(f"Response status: {response.status_code}")
    print(f"Response: {response.json()}")

def check_messages():
    """Check current messages"""
    print("\n📋 Checking current messages...")
    response = requests.get(f"{BASE_URL}/messages")
    
    if response.status_code == 200:
        messages = response.json()
        print(f"Total messages: {len(messages)}")
        
        # Check for any 1970 timestamps
        invalid_count = 0
        for msg in messages:
            if "1970" in str(msg.get("created_at", "")):
                invalid_count += 1
                print(f"❌ Found 1970 timestamp: {msg}")
        
        if invalid_count == 0:
            print("✅ No 1970 timestamps found")
        else:
            print(f"❌ Found {invalid_count} messages with 1970 timestamps")
    else:
        print(f"Failed to get messages: {response.status_code}")

if __name__ == "__main__":
    print("🧪 Testing timestamp validation fixes...\n")
    
    # Check initial state
    check_messages()
    
    # Test webhook with invalid timestamps
    test_webhook_with_invalid_timestamp()
    
    # Check messages after webhook tests
    check_messages()
    
    # Test cleanup
    test_cleanup_endpoint()
    
    # Check final state
    check_messages()
