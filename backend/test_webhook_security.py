"""
Quick Security Test for Webhook API Key Authentication

This script tests the webhook endpoint security by:
1. Testing with valid API key (should succeed)
2. Testing without API key (should fail with 401)
3. Testing with invalid API key (should fail with 401)
"""

import requests
import json
import os
from datetime import datetime

# Load environment variables
try:
    from dotenv import load_dotenv
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, '.env')
    
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"📁 Loaded environment from: {env_path}")
    else:
        print("❌ .env file not found")
        exit(1)
except ImportError:
    print("⚠️  python-dotenv not installed")
    exit(1)

# Get valid API key from environment
VALID_API_KEY = os.getenv('WEBHOOK_API_KEY')
if not VALID_API_KEY:
    print("❌ WEBHOOK_API_KEY not found in .env file")
    exit(1)

def test_webhook_security(production=False):
    """Test webhook security with different authentication scenarios"""
    
    base_url = "https://respondr.paincave.pro" if production else "http://localhost:8000"
    webhook_url = f"{base_url}/webhook"
    mode = "Production" if production else "Local"
    
    print(f"🔐 Testing Webhook Security - {mode} Mode")
    print("=" * 50)
    print(f"Endpoint: {webhook_url}")
    print()
    
    # Test message data
    test_message = {
        "name": "Security Test User",
        "text": "Testing webhook security with SAR-1, ETA 15 minutes",
        "created_at": int(datetime.now().timestamp())
    }
    
    # Test scenarios
    scenarios = [
        {
            "name": "Valid API Key",
            "headers": {
                'Content-Type': 'application/json',
                'X-API-Key': VALID_API_KEY
            },
            "expected_status": 200,
            "expected_result": "✅ SUCCESS"
        },
        {
            "name": "No API Key",
            "headers": {
                'Content-Type': 'application/json'
                # No X-API-Key header
            },
            "expected_status": 401,
            "expected_result": "❌ FAIL (401 Unauthorized)"
        },
        {
            "name": "Invalid API Key",
            "headers": {
                'Content-Type': 'application/json',
                'X-API-Key': 'invalid-key-12345'
            },
            "expected_status": 401,
            "expected_result": "❌ FAIL (401 Unauthorized)"
        },
        {
            "name": "Empty API Key",
            "headers": {
                'Content-Type': 'application/json',
                'X-API-Key': ''
            },
            "expected_status": 401,
            "expected_result": "❌ FAIL (401 Unauthorized)"
        }
    ]
    
    results = []
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] Testing: {scenario['name']}")
        print(f"   Expected: {scenario['expected_result']}")
        
        try:
            response = requests.post(webhook_url, json=test_message, headers=scenario['headers'], timeout=10)
            
            # Check if the response matches expected status
            if response.status_code == scenario['expected_status']:
                print(f"   Result: ✅ PASS - Got expected status {response.status_code}")
                results.append(True)
                
                # Show response details for debugging
                if response.status_code == 200:
                    print(f"   Response: Success - Message processed")
                else:
                    try:
                        error_detail = response.json().get('detail', 'No detail provided')
                        print(f"   Error: {error_detail}")
                    except:
                        print(f"   Error: {response.text[:100]}")
            else:
                print(f"   Result: ❌ FAIL - Got {response.status_code}, expected {scenario['expected_status']}")
                results.append(False)
                print(f"   Response: {response.text[:200]}")
                
        except requests.exceptions.RequestException as e:
            print(f"   Result: ❌ ERROR - Request failed: {e}")
            results.append(False)
        
        print()
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("=" * 50)
    print(f"🎯 Security Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All security tests PASSED - API key authentication is working correctly!")
        print("   • Valid API key: Allowed access ✅")
        print("   • No API key: Blocked access ❌")
        print("   • Invalid API key: Blocked access ❌")
        print("   • Empty API key: Blocked access ❌")
    else:
        print("⚠️  Some security tests FAILED - Check webhook authentication configuration!")
        
        for i, (scenario, result) in enumerate(zip(scenarios, results)):
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"   • {scenario['name']}: {status}")
    
    return passed == total

def main():
    """Run security tests for both local and production if requested"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test webhook API key security")
    parser.add_argument("--production", action="store_true", help="Test production endpoint")
    parser.add_argument("--local", action="store_true", help="Test local endpoint")
    parser.add_argument("--both", action="store_true", help="Test both local and production")
    
    args = parser.parse_args()
    
    if not any([args.production, args.local, args.both]):
        # Default to local if no option specified
        args.local = True
    
    all_passed = True
    
    if args.local or args.both:
        print("🏠 Testing Local Webhook Security")
        local_passed = test_webhook_security(production=False)
        all_passed = all_passed and local_passed
        
        if args.both:
            print("\n" + "="*60 + "\n")
    
    if args.production or args.both:
        print("🌐 Testing Production Webhook Security")
        prod_passed = test_webhook_security(production=True)
        all_passed = all_passed and prod_passed
    
    print("\n" + "="*60)
    if all_passed:
        print("🎉 All webhook security tests PASSED!")
        print("Your API key authentication is properly configured.")
    else:
        print("⚠️  Some webhook security tests FAILED!")
        print("Please check your API key authentication configuration.")

if __name__ == "__main__":
    main()
