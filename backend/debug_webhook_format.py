#!/usr/bin/env python3
"""
Test the exact same call that the webhook makes
"""
import os
import sys
sys.path.append('.')

from main import extract_details_from_text

def test_webhook_format():
    """Test with the exact format used by webhook"""
    
    display_name = "Debug Test - Length Check"
    text = "Responding with SAR-77, ETA 9:15"
    
    # This is exactly what the webhook does
    webhook_input = f"Sender: {display_name}. Message: {text}"
    
    print(f"Webhook input: {webhook_input}")
    print(f"FAST_LOCAL_PARSE: {os.getenv('FAST_LOCAL_PARSE', 'Not set')}")
    
    try:
        result = extract_details_from_text(webhook_input)
        print(f"Result: {result}")
        print(f"ETA: '{result.get('eta')}' (length: {len(result.get('eta', ''))})")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_webhook_format()
