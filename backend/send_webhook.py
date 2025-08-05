#!/usr/bin/env python3
"""
Simple webhook sender for testing individual messages
Usage: python send_webhook.py --production --name "John Doe" --message "Taking SAR78, ETA 15 minutes"
"""

import requests
import argparse
import json
import time
from datetime import datetime

def send_webhook(name, message, endpoint="http://localhost:8000/webhook", production=False):
    """Send a single webhook message"""
    
    if production:
        endpoint = "https://respondr.paincave.pro/webhook"
    
    webhook_data = {
        "name": name,
        "text": message,
        "created_at": int(datetime.now().timestamp())
    }
    
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'GroupMe-Webhook-Test/1.0'
    }
    
    print(f"📤 Sending webhook to: {endpoint}")
    print(f"👤 From: {name}")
    print(f"💬 Message: {message}")
    print("-" * 50)
    
    try:
        response = requests.post(endpoint, json=webhook_data, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print("✅ Webhook sent successfully!")
            try:
                result = response.json()
                print(f"📋 Response: {json.dumps(result, indent=2)}")
            except json.JSONDecodeError:
                print(f"📋 Response: {response.text}")
            return True
        else:
            print(f"❌ Failed to send webhook: HTTP {response.status_code}")
            print(f"📋 Error: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Send individual webhook messages to Respondr",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python send_webhook.py --name "John Smith" --message "Taking SAR78, ETA 15 minutes"
  python send_webhook.py --production --name "Sarah Johnson" --message "Responding with POV, ETA 20 mins"
  python send_webhook.py --production --name "Mike Wilson" --message "Got SAR-4, arriving at 23:30"
        """
    )
    
    parser.add_argument(
        "--name", 
        required=True,
        help="Name of the person sending the message"
    )
    
    parser.add_argument(
        "--message", 
        required=True,
        help="The message text (response content)"
    )
    
    parser.add_argument(
        "--production", 
        action="store_true",
        help="Send to production endpoint (https://respondr.paincave.pro)"
    )
    
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8000/webhook",
        help="Custom webhook endpoint URL (overrides --production)"
    )
    
    args = parser.parse_args()
    
    # Use custom endpoint if provided, otherwise use production flag
    if args.endpoint != "http://localhost:8000/webhook":
        endpoint = args.endpoint
        production = False
    else:
        endpoint = args.endpoint
        production = args.production
    
    success = send_webhook(
        name=args.name,
        message=args.message,
        endpoint=endpoint,
        production=production
    )
    
    if success:
        if production or "respondr.paincave.pro" in endpoint:
            print("\n🌐 Production webhook sent!")
            print("📝 To view results:")
            print("   1. Visit: https://respondr.paincave.pro")
            print("   2. Sign in with Azure AD credentials")
            print("   3. Check dashboard for your message")
        else:
            print("\n🏠 Local webhook sent!")
            print("📝 To view results:")
            print("   - Dashboard: http://localhost:8000")
            print("   - API: http://localhost:8000/api/responders")
        
        exit(0)
    else:
        print("\n❌ Failed to send webhook")
        exit(1)

if __name__ == "__main__":
    main()
