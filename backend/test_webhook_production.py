import requests
import json
import time
import os
import argparse
from datetime import datetime, timedelta
from urllib.parse import urljoin

class WebhookTester:
    """Enhanced webhook tester that supports both local and production endpoints with OAuth2"""
    
    def __init__(self, base_url="http://localhost:8000", use_production=False):
        self.base_url = base_url.rstrip('/')
        self.use_production = use_production
        
        # Determine the correct endpoints
        if use_production:
            self.webhook_url = f"{base_url}/webhook"
            self.api_url = f"{base_url}/api/responders"
            self.dashboard_url = base_url
            print(f"🌐 Production Mode: Testing {base_url}")
            print("📝 Note: Production API endpoints require OAuth2 authentication")
            print("📝 Note: Webhook endpoint bypasses authentication for external services")
        else:
            self.webhook_url = f"{base_url}/webhook"
            self.api_url = f"{base_url}/api/responders"
            self.dashboard_url = base_url
            print(f"🏠 Local Mode: Testing {base_url}")
    
    def send_webhook_message(self, message_data):
        """Send a single message to the webhook endpoint"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'GroupMe-Webhook-Test/1.0'
        }
        
        try:
            response = requests.post(
                self.webhook_url, 
                json=message_data, 
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"✅ {message_data['name']}: {message_data['text'][:50]}...")
                try:
                    result = response.json()
                    if 'status' in result:
                        print(f"   Response: {result['status']}")
                    return True
                except json.JSONDecodeError:
                    print(f"   Response: {response.text}")
                    return True
            else:
                print(f"❌ {message_data['name']}: HTTP {response.status_code}")
                print(f"   Error: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ {message_data['name']}: Connection error - {e}")
            return False
    
    def validate_api_responses(self):
        """Validate API responses - note: production requires authentication"""
        print("\n🔍 Validating API Responses...")
        print("-" * 40)
        
        if self.use_production:
            print("⚠️  Production API validation requires OAuth2 authentication")
            print("   Manual verification steps:")
            print(f"   1. Visit: {self.dashboard_url}")
            print("   2. Sign in with Azure AD credentials")
            print(f"   3. Check API: {self.api_url}")
            print(f"   4. Verify webhook data is processed correctly")
            return True
        
        try:
            response = requests.get(self.api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ API Response: {len(data)} responders")
                
                # Analyze the response data
                vehicle_types = {}
                eta_info = {"with_eta": 0, "without_eta": 0}
                
                for responder in data:
                    # Count vehicle types
                    vehicle = responder.get('vehicle', 'unknown')
                    vehicle_types[vehicle] = vehicle_types.get(vehicle, 0) + 1
                    
                    # Count ETA information
                    if responder.get('eta'):
                        eta_info["with_eta"] += 1
                    else:
                        eta_info["without_eta"] += 1
                
                print("\n📊 Response Analysis:")
                print(f"   Vehicle Types: {dict(vehicle_types)}")
                print(f"   ETA Information: {eta_info}")
                
                # Show recent responders
                recent_responders = [r for r in data if r.get('eta')][:5]
                if recent_responders:
                    print(f"\n🚀 Recent Responders with ETA:")
                    for resp in recent_responders:
                        vehicle = resp.get('vehicle', 'Unknown')
                        eta = resp.get('eta', 'Unknown')
                        print(f"   {resp['name']}: {vehicle} - ETA {eta}")
                
                return True
            else:
                print(f"❌ API Error: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ API Connection Error: {e}")
            return False
    
    def get_test_messages(self):
        """Generate comprehensive test messages"""
        now = datetime.now()
        
        return [
            # Valid standard responses - immediate timeframe
            {
                "name": "John Smith",
                "text": "I'm responding with SAR78, ETA 15 minutes",
                "created_at": int((now - timedelta(minutes=2)).timestamp()),
                "expected": "Valid SAR response - should show 15 min ETA"
            },
            {
                "name": "Sarah Johnson", 
                "text": "Taking my POV, should be there by 23:30",
                "created_at": int((now - timedelta(minutes=3)).timestamp()),
                "expected": "Valid POV response - should convert to 23:30"
            },
            {
                "name": "Mike Rodriguez",
                "text": "I'll take SAR-4, ETA 20 mins",
                "created_at": int((now - timedelta(minutes=1)).timestamp()),
                "expected": "Valid SAR response - should show 20 min ETA"
            },
            
            # Different ETA formats to test time conversion
            {
                "name": "Lisa Chen",
                "text": "Responding in my personal vehicle, about 25 minutes out",
                "created_at": int((now - timedelta(minutes=5)).timestamp()),
                "expected": "POV with duration - should calculate arrival time"
            },
            {
                "name": "David Wilson",
                "text": "Taking SAR rig, will be there in half an hour",
                "created_at": int((now - timedelta(minutes=10)).timestamp()),
                "expected": "SAR vehicle with 30 min duration"
            },
            
            # Production-specific webhook test
            {
                "name": "Production Test User",
                "text": f"Testing production webhook at {now.strftime('%H:%M:%S')} with SAR99",
                "created_at": int(now.timestamp()),
                "expected": "Production webhook authentication bypass test"
            },
            
            # Edge cases
            {
                "name": "Edge Case Tester",
                "text": "Maybe responding later, not sure about vehicle",
                "created_at": int((now - timedelta(minutes=12)).timestamp()),
                "expected": "Unclear response - should be classified appropriately"
            },
            {
                "name": "Non-Responder",
                "text": "What's the weather like up there?",
                "created_at": int((now - timedelta(minutes=15)).timestamp()),
                "expected": "Non-response message - should be filtered out"
            }
        ]
    
    def test_webhook_endpoint(self):
        """Run comprehensive webhook testing"""
        test_messages = self.get_test_messages()
        
        print("\n🧪 Enhanced Webhook Testing")
        print("=" * 60)
        print("Testing scenarios:")
        print("• Standard SAR vehicle assignments")
        print("• Personal vehicle (POV) responses") 
        print("• Partial/unclear information")
        print("• Non-response messages")
        print("• Production authentication bypass")
        print("=" * 60)
        
        if self.use_production:
            print("🔐 Production OAuth2 Configuration:")
            print("   ✅ Webhook endpoint: No authentication required")
            print("   🔒 Dashboard/API: OAuth2 authentication required")
            print("   🌐 This allows external services (GroupMe) to send webhooks")
        
        print(f"\nSending {len(test_messages)} messages to {self.webhook_url}")
        print("-" * 60)
        
        successful_sends = 0
        
        for i, message in enumerate(test_messages, 1):
            print(f"\n[{i:2d}/{len(test_messages)}] ", end="")
            if self.send_webhook_message(message):
                successful_sends += 1
            # Small delay between messages
            time.sleep(0.5 if self.use_production else 0.3)
        
        print("\n" + "=" * 60)
        print(f"Webhook Test Results: {successful_sends}/{len(test_messages)} messages sent successfully")
        
        if successful_sends == len(test_messages):
            print("\n🎉 All webhook messages sent successfully!")
            
            if self.use_production:
                print("\n🌐 Production Testing Complete!")
                print(f"   ✅ Webhook endpoint working: {self.webhook_url}")
                print(f"   🔐 Dashboard (requires auth): {self.dashboard_url}")
                print(f"   📊 API (requires auth): {self.api_url}")
                print("\n📝 Manual Verification Steps:")
                print(f"   1. Visit {self.dashboard_url} in browser")
                print("   2. Sign in with Azure AD credentials")
                print("   3. Verify test messages appear in dashboard")
                print("   4. Check API responses are correctly parsed")
            else:
                print("\n📋 Local Testing Complete!")
                print("   Analyzing parsed results...")
                self.validate_api_responses()
        else:
            failed_count = len(test_messages) - successful_sends
            print(f"\n⚠️  Warning: {failed_count} webhook messages failed")
            print("Check server connectivity and configuration.")
        
        return successful_sends == len(test_messages)

def main():
    parser = argparse.ArgumentParser(description="Test webhook endpoints for Respondr application")
    parser.add_argument(
        "--production", 
        action="store_true", 
        help="Test production endpoint with OAuth2 (default: local testing)"
    )
    parser.add_argument(
        "--url", 
        default="http://localhost:8000",
        help="Base URL for testing (default: http://localhost:8000 for local, https://respondr.paincave.pro for production)"
    )
    
    args = parser.parse_args()
    
    # Set default production URL if production flag is used
    if args.production and args.url == "http://localhost:8000":
        args.url = "https://respondr.paincave.pro"
    
    # Create and run tester
    tester = WebhookTester(base_url=args.url, use_production=args.production)
    success = tester.test_webhook_endpoint()
    
    if success:
        print("\n✅ All tests passed!")
        exit(0)
    else:
        print("\n❌ Some tests failed!")
        exit(1)

if __name__ == "__main__":
    main()
