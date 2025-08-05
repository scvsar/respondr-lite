"""
Respondr System Test Suite

This script provides comprehensive testing for the Respondr application.
Tests webhook functionality, API responses, and data processing.

Security Features:
- API key authentication via X-API-Key header
- Secrets loaded from .env file (not hardcoded)
- Automatic environment detection and setup

Usage:
  python test_system.py            # Test local endpoint
  python test_system.py --production  # Test production endpoint

Prerequisites:
- Run deployment/create-secrets.ps1 to generate .env file with current API keys
- Or manually set WEBHOOK_API_KEY environment variable
"""

import requests
import json
import time
import argparse
import os
from datetime import datetime, timedelta

# Try to load from environment variables or .env file
try:
    from dotenv import load_dotenv
    # Look for .env file in the same directory as this script
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, '.env')
    
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"📁 Loaded environment from: {env_path}")
    else:
        load_dotenv()  # Try default locations
        print("📁 Loaded environment from default locations")
except ImportError:
    # If python-dotenv is not installed, just use environment variables
    print("⚠️  python-dotenv not installed, using system environment variables only")
    pass

# Get webhook API key from environment
WEBHOOK_API_KEY = os.getenv('WEBHOOK_API_KEY')

if not WEBHOOK_API_KEY:
    print("⚠️  WARNING: WEBHOOK_API_KEY not found in environment variables!")
    print("Please ensure you have:")
    print("1. Run the create-secrets.ps1 script to generate .env file")
    print("2. Or set WEBHOOK_API_KEY environment variable")
    print("3. Or install python-dotenv: pip install python-dotenv")
    exit(1)

def get_webhook_url(production=False):
    """Get the appropriate webhook URL based on environment"""
    if production:
        return "https://respondr.paincave.pro/webhook"
    else:
        return "http://localhost:8000/webhook"

def get_api_url(production=False):
    """Get the appropriate API URL based on environment"""
    if production:
        return "https://respondr.paincave.pro/api/responders"
    else:
        return "http://localhost:8000/api/responders"

# Synthetic test data simulating GroupMe messages from SAR responders
# Including both valid responses and edge cases with realistic timing
test_messages = [
    # Valid standard responses - immediate timeframe
    {
        "name": "John Smith",
        "text": "I'm responding with SAR78, ETA 15 minutes",
        "created_at": int((datetime.now() - timedelta(minutes=2)).timestamp()),
        "expected": "Valid SAR response - should show 15 min ETA"
    },
    {
        "name": "Sarah Johnson", 
        "text": "Taking my POV, should be there by 23:30",
        "created_at": int((datetime.now() - timedelta(minutes=3)).timestamp()),
        "expected": "Valid POV response - should convert to 23:30"
    },
    {
        "name": "Mike Rodriguez",
        "text": "I'll take SAR-4, ETA 20 mins",
        "created_at": int((datetime.now() - timedelta(minutes=1)).timestamp()),
        "expected": "Valid SAR response - should show 20 min ETA"
    },
    
    # Different ETA formats to test time conversion
    {
        "name": "Lisa Chen",
        "text": "Responding in my personal vehicle, about 25 minutes out",
        "created_at": int((datetime.now() - timedelta(minutes=5)).timestamp()),
        "expected": "POV with duration - should calculate arrival time"
    },
    {
        "name": "David Wilson",
        "text": "Taking SAR rig, will be there in half an hour",
        "created_at": int((datetime.now() - timedelta(minutes=10)).timestamp()),
        "expected": "SAR vehicle with 30 min duration"
    },
    {
        "name": "Amanda Taylor",
        "text": "Got SAR12, arriving at 22:45",
        "created_at": int((datetime.now() - timedelta(minutes=8)).timestamp()),
        "expected": "SAR vehicle with specific time"
    },
    
    # Edge cases - unclear or partial information
    {
        "name": "Robert Brown",
        "text": "I'm responding but not sure what vehicle yet, ETA unknown",
        "created_at": int((datetime.now() - timedelta(minutes=7)).timestamp()),
        "expected": "Vehicle unknown, ETA unknown"
    },
    {
        "name": "Jennifer Davis",
        "text": "Taking SAR-7, ETA depends on traffic",
        "created_at": int((datetime.now() - timedelta(minutes=6)).timestamp()),
        "expected": "Vehicle clear, ETA unclear"
    },
    {
        "name": "Chris Martinez",
        "text": "Will be there soon",
        "created_at": int((datetime.now() - timedelta(minutes=4)).timestamp()),
        "expected": "Both vehicle and ETA vague"
    },
    
    # Non-conforming data - not actually responding
    {
        "name": "Grace Lee",
        "text": "Hey everyone, just checking in. How's the weather up there?",
        "created_at": int((datetime.now() - timedelta(minutes=12)).timestamp()),
        "expected": "Casual chat, not responding"
    },
    {
        "name": "Tom Wilson",
        "text": "I can't make it tonight, family emergency",
        "created_at": int((datetime.now() - timedelta(minutes=15)).timestamp()),
        "expected": "Not responding"
    },
    {
        "name": "Alex Chen",
        "text": "Does anyone have the coordinates for the LKP?",
        "created_at": int((datetime.now() - timedelta(minutes=9)).timestamp()),
        "expected": "Question, not response"
    },
    
    # Malformed or strange input
    {
        "name": "Emily Anderson",
        "text": "",
        "created_at": int((datetime.now() - timedelta(minutes=11)).timestamp()),
        "expected": "Empty message"
    },
    {
        "name": "Test User",
        "text": "🚗🕐💨",
        "created_at": int(datetime.now().timestamp()),
        "expected": "Emoji only"
    },
    {
        "name": "Mark Johnson",
        "text": "SAR SAR SAR ETA ETA vehicle vehicle 30 45 POV SAR12",
        "created_at": int((datetime.now() - timedelta(minutes=13)).timestamp()),
        "expected": "Confusing repeated keywords"
    },
    
    # Valid but unusual formats - test time parsing
    {
        "name": "Kelly Roberts",
        "text": "Driving my personal vehicle, approximately 1 hour until arrival",
        "created_at": int((datetime.now() - timedelta(minutes=14)).timestamp()),
        "expected": "Verbose POV response with 1 hour duration"
    },
    {
        "name": "Steve Miller",
        "text": "Got the big rig (SAR-7), will be there at 11:45 PM",
        "created_at": int((datetime.now() - timedelta(minutes=16)).timestamp()),
        "expected": "SAR vehicle with 12-hour time format"
    },
    {
        "name": "Nina Patel",
        "text": "responding ETA 5min POV",
        "created_at": int((datetime.now() - timedelta(seconds=30)).timestamp()),
        "expected": "Terse but valid response - arriving very soon"
    }
]

def send_webhook_message(message_data, production=False):
    """Send a single webhook message to the API"""
    webhook_url = get_webhook_url(production)
    
    try:
        # Remove the 'expected' field before sending (it's just for our testing reference)
        webhook_data = {k: v for k, v in message_data.items() if k != 'expected'}
        
        # Prepare headers with API key for authentication
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Add API key for production (and local if available)
        if WEBHOOK_API_KEY:
            headers['X-API-Key'] = WEBHOOK_API_KEY
        elif production:
            print(f"⚠️  Warning: No API key available for production request")
        
        response = requests.post(webhook_url, json=webhook_data, headers=headers)
        if response.status_code == 200:
            expected = message_data.get('expected', 'Standard test')
            print(f"[SENT] Sent from {message_data['name']}: '{message_data['text'][:40]}...'")
            print(f"   Expected: {expected}")
            return True
        else:
            print(f"[FAIL] Failed to send message from {message_data['name']}: {response.status_code}")
            if response.status_code == 401:
                print(f"   Authentication failed - check API key")
            return False
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Error sending message from {message_data['name']}: {e}")
        return False

def validate_api_responses(production=False):
    """Fetch and analyze the API responses after sending test data"""
    api_url = get_api_url(production)
    
    if production:
        print("\n⚠️  Production API validation requires OAuth2 authentication")
        print("   Please manually verify in browser:")
        print(f"   1. Visit: https://respondr.paincave.pro")
        print("   2. Sign in with Azure AD credentials")
        print(f"   3. Check API: {api_url}")
        return True
    
    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            responders = response.json()
            print(f"\nAnalysis of {len(responders)} processed messages:")
            
            # Categorize responses
            valid_responses = []
            not_responding = []
            unknown_vehicle = []
            unknown_eta = []
            time_converted = []
            
            for resp in responders:
                vehicle = resp.get('vehicle', '').lower()
                eta = resp.get('eta', '').lower()
                minutes_out = resp.get('minutes_until_arrival')
                
                if vehicle == 'not responding':
                    not_responding.append(resp['name'])
                elif vehicle == 'unknown':
                    unknown_vehicle.append(resp['name'])
                elif eta == 'unknown':
                    unknown_eta.append(resp['name'])
                else:
                    valid_responses.append(resp['name'])
                    
                # Check if ETA was converted to time format
                if eta and ':' in eta and len(eta) == 5:  # HH:MM format
                    time_converted.append(resp['name'])
            
            print(f"Clear responses: {len(valid_responses)}")
            print(f"Not responding: {len(not_responding)}")
            print(f"Unknown vehicle: {len(unknown_vehicle)}")
            print(f"Unknown ETA: {len(unknown_eta)}")
            print(f"Time format converted: {len(time_converted)}")
            
            if time_converted:
                print(f"   Time conversions: {', '.join(time_converted[:3])}{'...' if len(time_converted) > 3 else ''}")
            
            if not_responding:
                print(f"   Non-responders: {', '.join(not_responding)}")
            
            # Show some examples of time calculations
            arriving_soon = [r for r in responders if r.get('minutes_until_arrival') and r['minutes_until_arrival'] <= 15]
            if arriving_soon:
                print(f"\nArriving Soon (≤15 min): {len(arriving_soon)} responders")
                for resp in arriving_soon[:3]:  # Show first 3
                    print(f"   {resp['name']}: {resp['eta']} ({resp['minutes_until_arrival']} min)")
            
            return True
        else:
            print(f"[FAIL] Failed to fetch API data: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Error validating API responses: {e}")
        return False

def test_webhook_endpoint(production=False):
    """Send all test messages to the webhook endpoint"""
    webhook_url = get_webhook_url(production)
    mode = "Production" if production else "Local"
    
    print(f"Starting Enhanced Webhook Test - {mode} Mode")
    print("="*60)
    
    if production:
        print("Production testing with OAuth2 configuration:")
        print("• Webhook endpoint: No authentication required")
        print("• Dashboard/API: OAuth2 authentication required")
        print("• Testing webhook bypass functionality")
    else:
        print("Local testing scenarios:")
        print("• Standard SAR vehicle assignments")
        print("• Personal vehicle (POV) responses") 
        print("• Partial/unclear information")
        print("• Non-response messages (chat, questions)")
        print("• Malformed or empty messages")
        print("• Unusual but valid formats")
    
    print("="*60)
    print(f"Sending {len(test_messages)} messages to {webhook_url}")
    print("-" * 60)
    
    successful_sends = 0
    
    for i, message in enumerate(test_messages, 1):
        print(f"\n[{i:2d}/{len(test_messages)}] ", end="")
        if send_webhook_message(message, production):
            successful_sends += 1
        # Small delay between messages to simulate real-world timing
        time.sleep(0.5 if production else 0.3)
    
    print("\n" + "="*60)
    print(f"Test Results: {successful_sends}/{len(test_messages)} messages sent successfully")
    
    if successful_sends == len(test_messages):
        print(f"\nAll messages sent successfully to {mode.lower()} endpoint!")
        
        if production:
            print("\nProduction Webhook Testing Complete!")
            print("   Webhook endpoint bypasses OAuth2 authentication")
            print("   Manual verification required for processed data:")
            print("   1. Visit: https://respondr.paincave.pro")
            print("   2. Sign in with Azure AD credentials")
            print("   3. Verify test messages appear in dashboard")
        else:
            print("\nLocal Testing - Review the parsed results:")
            print("   - API endpoint: http://localhost:8000/api/responders")
            print("   - Dashboard: http://localhost:8000/dashboard") 
            print("   - Frontend: http://localhost:8000")
            print("\nCheck how the AI handled:")
            print("   • Valid responses vs. non-response messages")
            print("   • Unclear vehicle assignments")
            print("   • Missing or vague ETA information")
            print("   • Malformed input data")
        
        # Analyze the results
        validate_api_responses(production)
    else:
        print(f"\nWarning: {len(test_messages) - successful_sends} messages failed to send.")
        if production:
            print("Check production endpoint connectivity and OAuth2 configuration.")
        else:
            print("Check if the server is running on the correct port.")
            print("Expected server: http://localhost:8000")

def main():
    """Main function with argument parsing for production testing"""
    parser = argparse.ArgumentParser(description="Test webhook endpoints for Respondr application")
    parser.add_argument(
        "--production", 
        action="store_true", 
        help="Test production endpoint (https://respondr.paincave.pro)"
    )
    
    args = parser.parse_args()
    
    # Run the tests
    test_webhook_endpoint(production=args.production)

if __name__ == "__main__":
    main()
