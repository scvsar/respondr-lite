#!/usr/bin/env python3
"""
Script to send GroupMe test messages to the local webhook endpoint.
"""

import json
import requests
import time
import sys
from pathlib import Path

# Configuration
WEBHOOK_URL = "http://localhost:8000/webhook"
TEST_MESSAGES_FILE = "groupme_test_messages.json"
DELAY_BETWEEN_MESSAGES = 1.0  # seconds
TIMEOUT = 30  # seconds

def load_test_messages():
    """Load the test messages from JSON file."""
    try:
        with open(TEST_MESSAGES_FILE, 'r') as f:
            messages = json.load(f)
        print(f"Loaded {len(messages)} test messages")
        return messages
    except FileNotFoundError:
        print(f"Error: {TEST_MESSAGES_FILE} not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        sys.exit(1)

def send_message(message, index):
    """Send a single message to the webhook endpoint."""
    try:
        print(f"Sending message {index + 1}: '{message['text'][:50]}...' from {message['name']}")
        
        response = requests.post(
            WEBHOOK_URL,
            json=message,
            headers={'Content-Type': 'application/json'},
            timeout=TIMEOUT
        )
        
        if response.status_code == 200:
            print(f"  ✅ Success: {response.status_code}")
            return True
        else:
            print(f"  ❌ Failed: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"  ❌ Connection error - is the server running on {WEBHOOK_URL}?")
        return False
    except requests.exceptions.Timeout:
        print(f"  ❌ Timeout after {TIMEOUT} seconds")
        return False
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Request error: {e}")
        return False

def main():
    """Main function to send all test messages."""
    print("GroupMe Test Message Sender")
    print("=" * 40)
    print(f"Target URL: {WEBHOOK_URL}")
    print(f"Delay between messages: {DELAY_BETWEEN_MESSAGES}s")
    print()
    
    # Load messages
    messages = load_test_messages()
    
    # Send messages
    success_count = 0
    total_count = len(messages)
    
    for i, message in enumerate(messages):
        if send_message(message, i):
            success_count += 1
        
        # Add delay between messages (except for the last one)
        if i < total_count - 1:
            time.sleep(DELAY_BETWEEN_MESSAGES)
    
    # Summary
    print()
    print("=" * 40)
    print(f"Summary: {success_count}/{total_count} messages sent successfully")
    
    if success_count == total_count:
        print("🎉 All messages sent successfully!")
        sys.exit(0)
    else:
        print("⚠️  Some messages failed to send")
        sys.exit(1)

if __name__ == "__main__":
    main()