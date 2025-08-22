#!/usr/bin/env python3
"""
Script to send a small sample of GroupMe test messages to the local webhook endpoint.
Useful for quick testing without sending all messages.
"""

import json
import requests
import time
import sys

# Configuration
WEBHOOK_URL = "http://localhost:8000/webhook"
SAMPLE_MESSAGES_FILE = "groupme_sample_messages.json"
DELAY_BETWEEN_MESSAGES = 2.0  # seconds (longer delay for easier observation)
TIMEOUT = 30  # seconds

def load_sample_messages():
    """Load the sample messages from JSON file."""
    try:
        with open(SAMPLE_MESSAGES_FILE, 'r') as f:
            messages = json.load(f)
        print(f"Loaded {len(messages)} sample messages")
        return messages
    except FileNotFoundError:
        print(f"Error: {SAMPLE_MESSAGES_FILE} not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        sys.exit(1)

def send_message(message, index):
    """Send a single message to the webhook endpoint."""
    try:
        print(f"\nMessage {index + 1}:")
        print(f"  From: {message['name']}")
        print(f"  Text: {message['text']}")
        print(f"  Group: {message['group_id']}")
        print(f"  Sending to {WEBHOOK_URL}...")
        
        response = requests.post(
            WEBHOOK_URL,
            json=message,
            headers={'Content-Type': 'application/json'},
            timeout=TIMEOUT
        )
        
        if response.status_code == 200:
            print(f"  ✅ Success: {response.status_code}")
            if response.text:
                print(f"  Response: {response.text}")
            return True
        else:
            print(f"  ❌ Failed: {response.status_code}")
            if response.text:
                print(f"  Error: {response.text}")
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
    """Main function to send sample test messages."""
    print("GroupMe Sample Message Sender")
    print("=" * 50)
    print(f"Target URL: {WEBHOOK_URL}")
    print(f"Delay between messages: {DELAY_BETWEEN_MESSAGES}s")
    print("This will send a small sample for testing")
    
    # Load messages
    messages = load_sample_messages()
    
    # Send messages
    success_count = 0
    total_count = len(messages)
    
    for i, message in enumerate(messages):
        if send_message(message, i):
            success_count += 1
        
        # Add delay between messages (except for the last one)
        if i < total_count - 1:
            print(f"  Waiting {DELAY_BETWEEN_MESSAGES}s before next message...")
            time.sleep(DELAY_BETWEEN_MESSAGES)
    
    # Summary
    print("\n" + "=" * 50)
    print(f"Summary: {success_count}/{total_count} messages sent successfully")
    
    if success_count == total_count:
        print("🎉 All sample messages sent successfully!")
        sys.exit(0)
    else:
        print("⚠️  Some messages failed to send")
        sys.exit(1)

if __name__ == "__main__":
    main()