#!/usr/bin/env python3
"""
Test script to verify the enhanced LLM retry logic and logging.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.llm import extract_details_from_text
from datetime import datetime
import logging

# Set up logging to see the retry behavior
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def test_llm_retry():
    """Test the LLM retry functionality with a simple message."""
    
    print("Testing LLM retry logic...")
    print("=" * 50)
    
    # Test with a simple message that should trigger LLM processing
    test_message = "Randy responding ETA 10:30"
    
    try:
        result = extract_details_from_text(
            text=test_message,
            base_time=datetime.now(),
            prev_eta_iso=None,
            debug=True
        )
        
        print(f"Input message: '{test_message}'")
        print(f"Result: {result}")
        print("\nKey fields:")
        print(f"  Vehicle: {result.get('vehicle', 'N/A')}")
        print(f"  Status: {result.get('raw_status', 'N/A')}")
        print(f"  ETA: {result.get('eta', 'N/A')}")
        print(f"  Parse source: {result.get('parse_source', 'N/A')}")
        
        if result.get('_llm_error'):
            print(f"  LLM Error: {result['_llm_error']}")
        
        return True
        
    except Exception as e:
        print(f"Test failed with exception: {e}")
        return False

if __name__ == "__main__":
    success = test_llm_retry()
    if success:
        print("\n✅ Test completed successfully!")
        print("\nCheck the logs above to see the retry behavior and token usage logging.")
    else:
        print("\n❌ Test failed!")
    
    print("\nConfiguration values being used:")
    from app.config import (
        LLM_MAX_RETRIES, LLM_TOKEN_INCREASE_FACTOR, 
        DEFAULT_MAX_COMPLETION_TOKENS, MAX_COMPLETION_TOKENS_CAP
    )
    print(f"  LLM_MAX_RETRIES: {LLM_MAX_RETRIES}")
    print(f"  LLM_TOKEN_INCREASE_FACTOR: {LLM_TOKEN_INCREASE_FACTOR}")
    print(f"  DEFAULT_MAX_COMPLETION_TOKENS: {DEFAULT_MAX_COMPLETION_TOKENS}")
    print(f"  MAX_COMPLETION_TOKENS_CAP: {MAX_COMPLETION_TOKENS_CAP}")
