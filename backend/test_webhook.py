import requests
import json
import time
from datetime import datetime, timedelta

# Base URL for the webhook endpoint
WEBHOOK_URL = "http://localhost:8000/webhook"

# Synthetic test data simulating GroupMe messages from SAR responders
test_messages = [
    {
        "name": "John Smith",
        "text": "I'm responding with SAR78, ETA 15 minutes",
        "created_at": int((datetime.now() - timedelta(minutes=10)).timestamp())
    },
    {
        "name": "Sarah Johnson",
        "text": "Taking my POV, should be there by 23:30",
        "created_at": int((datetime.now() - timedelta(minutes=9)).timestamp())
    },
    {
        "name": "Mike Rodriguez",
        "text": "I'll take SAR-4, ETA 20 mins",
        "created_at": int((datetime.now() - timedelta(minutes=8)).timestamp())
    },
    {
        "name": "Lisa Chen",
        "text": "Responding in personal vehicle, about 25 minutes out",
        "created_at": int((datetime.now() - timedelta(minutes=7)).timestamp())
    },
    {
        "name": "David Wilson",
        "text": "I have the SAR rig, will be there at 23:45",
        "created_at": int((datetime.now() - timedelta(minutes=6)).timestamp())
    },
    {
        "name": "Amanda Taylor",
        "text": "Taking SAR12, ETA 30 minutes from now",
        "created_at": int((datetime.now() - timedelta(minutes=5)).timestamp())
    },
    {
        "name": "Robert Brown",
        "text": "I'm driving my own car, should arrive around midnight",
        "created_at": int((datetime.now() - timedelta(minutes=4)).timestamp())
    },
    {
        "name": "Jennifer Davis",
        "text": "Got SAR-7, will be there in 18 minutes",
        "created_at": int((datetime.now() - timedelta(minutes=3)).timestamp())
    },
    {
        "name": "Chris Martinez",
        "text": "Using POV, ETA 23:50",
        "created_at": int((datetime.now() - timedelta(minutes=2)).timestamp())
    },
    {
        "name": "Emily Anderson",
        "text": "I'll take the SAR vehicle, about 22 minutes out",
        "created_at": int((datetime.now() - timedelta(minutes=1)).timestamp())
    }
]

def send_webhook_message(message_data):
    """Send a single webhook message to the API"""
    try:
        response = requests.post(WEBHOOK_URL, json=message_data)
        if response.status_code == 200:
            print(f"Sent message from {message_data['name']}: {message_data['text'][:50]}...")
            return True
        else:
            print(f"Failed to send message from {message_data['name']}: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Error sending message from {message_data['name']}: {e}")
        return False

def test_webhook_endpoint():
    """Send all test messages to the webhook endpoint"""
    print("Starting webhook test with synthetic SAR responder data...")
    print(f"Sending {len(test_messages)} messages to {WEBHOOK_URL}")
    print("-" * 60)
    
    successful_sends = 0
    
    for i, message in enumerate(test_messages, 1):
        print(f"[{i}/{len(test_messages)}] ", end="")
        if send_webhook_message(message):
            successful_sends += 1
        
        # Small delay between messages to simulate real-world timing
        time.sleep(0.5)
    
    print("-" * 60)
    print(f"Test completed: {successful_sends}/{len(test_messages)} messages sent successfully")
    
    if successful_sends == len(test_messages):
        print("All messages sent successfully!")
        print("You can now view the results at:")
        print("   - Frontend: http://localhost:8000")
        print("   - API: http://localhost:8000/api/responders")
        print("   - Dashboard: http://localhost:8000/dashboard")
    else:
        print("Some messages failed to send. Check if the server is running.")

if __name__ == "__main__":
    test_webhook_endpoint()
