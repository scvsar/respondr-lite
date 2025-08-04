#!/usr/bin/env python3

"""
Simple test to verify Azure OpenAI connection and response parsing
"""

import os
import json
import logging
from dotenv import load_dotenv
from openai import AzureOpenAI

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def test_azure_openai_connection():
    """Test basic Azure OpenAI connection"""
    
    # Get environment variables
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") 
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    
    print("Configuration Check:")
    print(f"   API Key: {'✅ Present' if api_key else '❌ Missing'}")
    print(f"   Endpoint: {endpoint or '❌ Missing'}")
    print(f"   Deployment: {deployment or '❌ Missing'}")
    print(f"   API Version: {api_version or '❌ Missing'}")
    
    if not all([api_key, endpoint, deployment, api_version]):
        print("❌ Missing required environment variables")
        return False
    
    try:
        # Initialize client
        client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )
        print("✅ Azure OpenAI client initialized")
        
        # Test simple message
        test_message = "I'm responding with SAR78, ETA 15 minutes"
        print(f"\n🧪 Testing with message: '{test_message}'")
        
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "user", 
                    "content": f"Extract vehicle and ETA from: '{test_message}'. Return JSON format: {{\"vehicle\": \"value\", \"eta\": \"value\"}}"
                }
            ],
            temperature=0,
            max_tokens=100
        )
        
        reply = response.choices[0].message.content
        print(f"Raw response: '{reply}'")
        
        # Try to parse as JSON
        try:
            parsed = json.loads(reply)
            print(f"✅ Successfully parsed JSON: {parsed}")
            
            if 'vehicle' in parsed and 'eta' in parsed:
                print(f"✅ Contains required fields")
                print(f"   Vehicle: {parsed['vehicle']}")
                print(f"   ETA: {parsed['eta']}")
                return True
            else:
                print(f"❌ Missing required fields in JSON")
                return False
                
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse as JSON: {e}")
            print("   This might be why all responses are 'Unknown'")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_multiple_scenarios():
    """Test various message scenarios including time conversion"""
    
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    
    if not all([api_key, endpoint, deployment, api_version]):
        print("❌ Skipping multiple scenarios test - missing config")
        return
    
    client = AzureOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        api_version=api_version,
    )
    
    from datetime import datetime
    current_time = datetime.now()
    current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
    current_time_short = current_time.strftime("%H:%M")
    
    test_cases = [
        "I'm responding with SAR78, ETA 15 minutes",
        "Taking my POV, should be there by 23:30", 
        "Got SAR-4, will be there in half an hour",
        "Using personal vehicle, about 45 minutes out",
        "Hey everyone, just checking in",
        "I can't make it tonight",
        ""
    ]
    
    print(f"\n🧪 Testing {len(test_cases)} scenarios with time conversion:")
    print(f"Current time: {current_time_str}")
    print("-" * 60)
    
    for i, test_msg in enumerate(test_cases, 1):
        print(f"\n[{i}] Testing: '{test_msg or '(empty)'}' ")
        
        try:
            prompt = f"""CURRENT TIME: {current_time_str} (24-hour format: {current_time_short})

Extract vehicle and ETA from: '{test_msg}'

Convert ETAs to 24-hour time format:
- Duration like '15 minutes' → add to current time
- Clock times like '23:30' → return as-is  
- If not responding, return "Not Responding"

Return JSON: {{"vehicle": "value", "eta": "HH:MM"}}"""

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0,
                max_tokens=100
            )
            
            reply = response.choices[0].message.content.strip()
            print(f"    Raw: '{reply}'")
            
            try:
                import json
                parsed = json.loads(reply)
                vehicle = parsed.get('vehicle', 'MISSING')
                eta = parsed.get('eta', 'MISSING')
                print(f"    ✅ Vehicle: {vehicle}")
                print(f"    ✅ ETA: {eta}")
                
                # Validate time format
                if eta and ':' in eta and len(eta) == 5:
                    print(f"    ⏰ Time format validated")
                elif eta in ['Unknown', 'Not Responding']:
                    print(f"    🚫 Non-response correctly identified")
                    
            except:
                print(f"    ❌ Failed to parse JSON")
                
        except Exception as e:
            print(f"    ❌ API Error: {e}")

if __name__ == "__main__":
    print("🚀 Azure OpenAI Connection Test")
    print("=" * 40)
    
    success = test_azure_openai_connection()
    
    if success:
        test_multiple_scenarios()
        print(f"\n✅ If this test passes but the main app still shows 'Unknown',")
        print(f"   check the server logs for detailed error messages.")
    else:
        print(f"\n❌ Basic connection test failed.")
        print(f"   This explains why all responses are 'Unknown'.")
        print(f"   Fix the configuration and try again.")
