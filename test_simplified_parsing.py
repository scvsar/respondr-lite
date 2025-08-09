#!/usr/bin/env python3
"""Test the simplified AI parsing approach without Azure OpenAI"""

import sys
sys.path.append('backend')

from main import extract_details_from_text
import os

# Set test mode to bypass Azure OpenAI requirements
os.environ['IS_TESTING'] = 'true'

def test_simplified_parsing():
    print("Testing simplified parsing approach...")
    
    # Test case 1: "Can't make it, sorry" should be Not Responding
    print("\n1. Testing 'Can't make it, sorry':")
    result = extract_details_from_text("Can't make it, sorry")
    print(f"   Result: {result}")
    print(f"   Expected: vehicle='Not Responding', eta='Not Responding'")
    
    # Test case 2: "ETA 9:15"
    print("\n2. Testing 'ETA 9:15':")
    result = extract_details_from_text("ETA 9:15")
    print(f"   Result: {result}")
    
    # Test case 3: "SAR-12 en route, 30 minutes"
    print("\n3. Testing 'SAR-12 en route, 30 minutes':")
    result = extract_details_from_text("SAR-12 en route, 30 minutes")
    print(f"   Result: {result}")
    
    print("\nDone!")

if __name__ == "__main__":
    test_simplified_parsing()
