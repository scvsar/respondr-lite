#!/usr/bin/env python3
"""
Debug script to check the live environment configuration
"""
import os
import sys
sys.path.append('.')

# Import our functions
from main import extract_details_from_text, convert_eta_to_timestamp

def debug_environment():
    """Check environment configuration"""
    print("🔍 Environment Debug")
    print("=" * 40)
    
    # Check environment variables
    print(f"FAST_LOCAL_PARSE: {os.getenv('FAST_LOCAL_PARSE', 'Not set')}")
    print(f"AZURE_OPENAI_API_KEY: {'Set' if os.getenv('AZURE_OPENAI_API_KEY') else 'Not set'}")
    print(f"AZURE_OPENAI_ENDPOINT: {os.getenv('AZURE_OPENAI_ENDPOINT', 'Not set')}")
    print(f"AZURE_OPENAI_DEPLOYMENT: {os.getenv('AZURE_OPENAI_DEPLOYMENT', 'Not set')}")
    
    print("\n🧪 Test Function Calls")
    print("=" * 40)
    
    # Test extract_details_from_text
    test_text = "Responding with SAR-99, ETA 9:15"
    print(f"Input: {test_text}")
    
    try:
        result = extract_details_from_text(test_text)
        print(f"extract_details_from_text result: {result}")
        
        # Test convert_eta_to_timestamp
        if result and result.get('eta'):
            eta_result = convert_eta_to_timestamp(result['eta'])
            print(f"convert_eta_to_timestamp('{result['eta']}'): {eta_result}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n🧪 Test 24:30 Case")
    print("=" * 40)
    
    test_text_2 = "Taking my POV, arriving at 24:30hrs"
    print(f"Input: {test_text_2}")
    
    try:
        result_2 = extract_details_from_text(test_text_2)
        print(f"extract_details_from_text result: {result_2}")
        
        if result_2 and result_2.get('eta'):
            eta_result_2 = convert_eta_to_timestamp(result_2['eta'])
            print(f"convert_eta_to_timestamp('{result_2['eta']}'): {eta_result_2}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_environment()
