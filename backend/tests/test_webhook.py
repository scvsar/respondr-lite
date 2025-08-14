"""
Enhanced Webhook Test Script for Respondr Application

This script tests the webhook endpoint with proper API key authentication.
The API key is securely loaded from environment variables or .env file.

Security Features:
- API key authentication via X-API-Key header
- Secrets loaded from .env file (not hardcoded)
- Automatic environment detection and setup

Usage:
  python tests/test_webhook.py            # Test local endpoint
  python tests/test_webhook.py --production  # Test production endpoint

Prerequisites:
- Run create-secrets.ps1 to generate .env file with current API keys
- Or manually set WEBHOOK_API_KEY environment variable
"""

import requests
import json
import time
import argparse
import os
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from openai import AzureOpenAI

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
# Azure OpenAI settings (optional for dynamic generation)
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

if not WEBHOOK_API_KEY:
    print("⚠️  WARNING: WEBHOOK_API_KEY not found in environment variables!")
    print("Please ensure you have:")
    print("1. Run the create-secrets.ps1 script to generate .env file")
    print("2. Or set WEBHOOK_API_KEY environment variable")
    print("3. Or install python-dotenv: pip install python-dotenv")
    # Not exiting to allow local dev without auth; webhook may skip auth in test mode.

def get_webhook_url(production: bool = False) -> str:
    """Get the appropriate webhook URL based on environment"""
    if production:
        return "https://respondr.rtreit.com/webhook"
    else:
        return "http://localhost:8000/webhook"

def get_api_url(production: bool = False) -> str:
    """Get the appropriate API URL based on environment"""
    if production:
        return "https://respondr.rtreit.com/api/responders"
    else:
        return "http://localhost:8000/api/responders"

def _default_seed_messages() -> List[Dict[str, Any]]:
    """Fallback static examples if AI generation is unavailable."""
    now = datetime.now()
    seeds = [
        {"name": "John Smith", "text": "I'm responding with SAR78, ETA 15 minutes"},
        {"name": "Sarah Johnson", "text": "Taking my POV, should be there by 23:30"},
        {"name": "Mike Rodriguez", "text": "I'll take SAR-4, ETA 20 mins"},
        {"name": "Lisa Chen", "text": "Responding in my personal vehicle, about 25 minutes out"},
        {"name": "David Wilson", "text": "Taking SAR rig, will be there in half an hour"},
        {"name": "Amanda Taylor", "text": "Got SAR12, arriving at 22:45"},
        {"name": "Robert Brown", "text": "I'm responding but not sure what vehicle yet, ETA unknown"},
        {"name": "Jennifer Davis", "text": "Taking SAR-7, ETA depends on traffic"},
        {"name": "Chris Martinez", "text": "Will be there soon"},
        {"name": "Grace Lee", "text": "Hey everyone, just checking in. How's the weather up there?"},
        {"name": "Tom Wilson", "text": "I can't make it tonight, family emergency"},
        {"name": "Alex Chen", "text": "Does anyone have the coordinates for the LKP?"},
        {"name": "Emily Anderson", "text": ""},
        {"name": "Test User", "text": "🚗🕐💨"},
        {"name": "Nina Patel", "text": "responding ETA 5min POV"},
    ]
    # Attach rolling created_at values
    out: List[Dict[str, Any]] = []
    for i, s in enumerate(seeds):
        out.append({
            **s,
            "created_at": int((now - timedelta(minutes=1 + i)).timestamp()),
            "expected": "seed"
        })
    return out

def _init_azure_client() -> Optional[AzureOpenAI]:
    if AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT:
        try:
            return AzureOpenAI(
                api_key=AZURE_OPENAI_API_KEY,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_version=AZURE_OPENAI_API_VERSION,
            )
        except Exception as e:
            print(f"⚠️  Failed to init Azure OpenAI client: {e}")
    else:
        print("ℹ️  Azure OpenAI env vars not set; using fallback messages.")
    return None

def generate_test_messages_via_ai(count: int = 15) -> List[Dict[str, Any]]:
    """Use Azure OpenAI to generate responder-like messages with names and texts."""
    client = _init_azure_client()
    if client is None:
        return _default_seed_messages()

    try:
        prompt = (
            f"Generate {count} realistic GroupMe-style SAR responder chat messages as a JSON array.\n"
            "Each array item must be an object with EXACTLY these fields: \n"
            "- name: a realistic human first and last name, e.g., 'Wilson Burkhart' (no digits, no codes like SAR/POV). You may optionally append a team tag in parentheses, e.g., '(OSU-4)'.\n"
            "- text: the message text only (do NOT include the name). Include vehicle and ETA wording in natural variations, e.g., 'Responding with SAR78 ETA 15 minutes', 'Taking POV arriving at 23:30', 'Can't make it', 'On scene', or non-response chatter.\n"
            "Include a mix of: clear SAR vehicle responses, POV responses, durations (5, 10, 20, 30 minutes, 1 hour, 'half hour'), absolute times (HH:MM or 12-hour), vague responses, empty/emoji, and off-topic messages.\n"
            "Return ONLY the JSON array with objects like: [{\"name\": \"First Last(OSU-4)\", \"text\": \"...\"}, ...]"
        )
        if not AZURE_OPENAI_DEPLOYMENT:
            raise RuntimeError("AZURE_OPENAI_DEPLOYMENT not set")
        resp = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=1200,
        )
        raw_content = resp.choices[0].message.content
        content = (raw_content or "").strip()
        # Extract JSON array
        start = content.find('[')
        end = content.rfind(']')
        if start != -1 and end != -1 and end > start:
            raw = content[start:end+1]
            items = json.loads(raw)
        else:
            items = json.loads(content)
        # Attach created_at and expected flags
        now = datetime.now()
        out: List[Dict[str, Any]] = []
        for i, it in enumerate(items[:count]):
            name = it.get("name") or f"User {i+1}"
            text = it.get("text") or ""
            out.append({
                "name": name,
                "text": text,
                "created_at": int((now - timedelta(minutes=i+1)).timestamp()),
                "expected": "ai"
            })
        # If too few, pad with seeds
        if len(out) < count:
            out.extend(_default_seed_messages()[: count - len(out)])
        return out
    except Exception as e:
        print(f"⚠️  AI generation failed, using fallback: {e}")
        return _default_seed_messages()

def to_groupme_payloads(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Wrap simple name/text items into GroupMe webhook payload shape."""
    result: List[Dict[str, Any]] = []
    for it in items:
        guid = str(uuid.uuid4()).upper()
        # Generate realistic numeric strings for IDs
        group_id = str(100000000 + abs(hash("group")) % 900000000)  # stable 9-digit
        now_ns = int(datetime.now().timestamp() * 1_000_000_000)
        id_str = str(now_ns)[-18:]  # 18-digit-like
        sender_id = str(30000000 + abs(hash(it.get('name', 'user'))) % 60000000)
        user_id = sender_id
        payload: Dict[str, Any] = {
            "attachments": [],
            "avatar_url": "https://i.groupme.com/1024x1024.jpeg.placeholder",
            "created_at": it.get("created_at", int(datetime.now().timestamp())),
            "group_id": group_id,
            "id": id_str,
            "name": it.get("name", "Responder One"),
            "sender_id": sender_id,
            "sender_type": "user",
            "source_guid": guid,
            "system": False,
            "text": it.get("text", ""),
            "user_id": user_id,
            "expected": it.get("expected", "")
        }
        result.append(payload)
    return result

def send_webhook_message(message_data: Dict[str, Any], production: bool = False) -> bool:
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

def validate_api_responses(production: bool = False) -> bool:
    """Fetch and analyze the API responses after sending test data"""
    api_url = get_api_url(production)
    
    if production:
        print("\n⚠️  Production API validation requires OAuth2 authentication")
        print("   Please manually verify in browser:")
        print(f"   1. Visit: https://respondr.rtreit.com")
        print("   2. Sign in with Azure AD credentials")
        print(f"   3. Check API: {api_url}")
        return True
    
    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            responders = response.json()
            print(f"\nAnalysis of {len(responders)} processed messages:")
            
            # Categorize responses
            valid_responses: List[str] = []
            not_responding: List[str] = []
            unknown_vehicle: List[str] = []
            unknown_eta: List[str] = []
            time_converted: List[str] = []
            
            for resp in responders:
                vehicle = resp.get('vehicle', '').lower()
                eta = resp.get('eta', '').lower()
                # minutes_out not needed in this validation summary
                
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

def test_webhook_endpoint(production: bool = False) -> None:
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
    # Build messages dynamically via AI (with fallback)
    base_items = generate_test_messages_via_ai(count=18)
    groupme_payloads = to_groupme_payloads(base_items)
    print(f"Sending {len(groupme_payloads)} messages to {webhook_url}")
    print("-" * 60)
    
    successful_sends = 0
    
    total = len(groupme_payloads)
    for i, message in enumerate(groupme_payloads, 1):
        print(f"\n[{i:2d}/{total}] ", end="")
        if send_webhook_message(message, production):
            successful_sends += 1
        # Small delay between messages to simulate real-world timing
        time.sleep(0.5 if production else 0.3)
    
    print("\n" + "="*60)
    print(f"Test Results: {successful_sends}/{len(groupme_payloads)} messages sent successfully")
    
    if successful_sends == len(groupme_payloads):
        print(f"\nAll messages sent successfully to {mode.lower()} endpoint!")
        
        if production:
            print("\nProduction Webhook Testing Complete!")
            print("   Webhook endpoint bypasses OAuth2 authentication")
            print("   Manual verification required for processed data:")
            print("   1. Visit: https://respondr.rtreit.com")
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
        print(f"\nWarning: {len(groupme_payloads) - successful_sends} messages failed to send.")
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
        help="Test production endpoint (https://respondr.rtreit.com)"
    )
    
    args = parser.parse_args()
    
    # Run the tests
    test_webhook_endpoint(production=args.production)

if __name__ == "__main__":
    main()
