#!/usr/bin/env python3
"""Additional tests for edge cases with simplified AI parsing"""

import sys
sys.path.append('backend')

from main import extract_details_from_text
import os

# Set test mode to bypass Azure OpenAI requirements
os.environ['IS_TESTING'] = 'true'

def test_edge_cases():
    print("Testing edge cases with simplified parsing...")
    
    # Test more decline variations
    decline_cases = [
        "Won't be able to make it",
        "Family emergency, can't respond", 
        "Not coming, sorry",
        "Cannot make it tonight",
        "Unable to respond"
    ]
    
    for i, text in enumerate(decline_cases, 1):
        print(f"\n{i}. Testing '{text}':")
        result = extract_details_from_text(text)
        print(f"   Result: {result}")
        if result.get('vehicle') == 'Not Responding' and result.get('eta') == 'Not Responding':
            print("   ✅ Correctly identified as Not Responding")
        else:
            print("   ❌ Failed to identify as Not Responding")
    
    # Test some normal responses
    normal_cases = [
        "POV, ETA 15 minutes",
        "SAR-56 responding, arrival 22:30",
        "On my way, 45 minutes out"
    ]
    
    for i, text in enumerate(normal_cases, len(decline_cases) + 1):
        print(f"\n{i}. Testing '{text}':")
        result = extract_details_from_text(text)
        print(f"   Result: {result}")
        if result.get('vehicle') != 'Not Responding' and result.get('eta') != 'Not Responding':
            print("   ✅ Correctly identified as responding")
        else:
            print("   ❌ Incorrectly marked as Not Responding")
    
    print("\nDone!")

if __name__ == "__main__":
    test_edge_cases()
