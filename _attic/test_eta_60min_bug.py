"""
Test case for the specific ETA 60min bug reported by user
This reproduces the exact scenario where AI returned 01:00 AM instead of 13:39 PM
"""

import sys
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv('backend/.env')

# Add backend directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_path = os.path.join(current_dir, 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Import the function we want to test
try:
    from main import extract_details_from_text
except ImportError as e:
    print(f"Error: Could not import extract_details_from_text from main.py: {e}")
    print(f"Current directory: {current_dir}")
    print(f"Backend path: {backend_path}")
    print("Make sure you're running this test from the respondr root directory")
    sys.exit(1)

def test_eta_60min_bug():
    """
    Test the specific case reported:
    - Message sent at 12:39 PM: "Responding SAR7 ETA 60min"
    - Expected ETA: 13:39 PM (12:39 + 60 minutes)
    - Actual AI result: 01:00 AM next day (WRONG!)
    """
    # Use the actual timestamp from the failing message
    message_timestamp = datetime(2025, 8, 11, 12, 39, 15)  # 12:39:15 PM
    message = "Responding SAR7 ETA 60min"
    
    print("================================================================================")
    print("ETA 60MIN BUG TEST")
    print("================================================================================")
    print(f"Message: '{message}'")
    print(f"Timestamp: {message_timestamp.strftime('%Y-%m-%d %H:%M:%S')} (12:39 PM)")
    print(f"Expected ETA: 13:39 (12:39 PM + 60 minutes)")
    print("--------------------------------------------------------------------------------")
    
    # Call the AI parsing function
    result = extract_details_from_text(message, message_timestamp)
    
    print(f"AI Result:")
    print(f"  Vehicle: {result.get('vehicle', 'Unknown')}")
    print(f"  ETA: {result.get('eta', 'Unknown')}")
    print(f"  Raw Status: {result.get('raw_status', 'Unknown')}")
    print(f"  Full Result: {result}")
    
    # Check if the result is correct
    expected_eta = "13:39"  # 12:39 + 60 minutes = 13:39
    actual_eta = result.get('eta', 'Unknown')
    
    print("--------------------------------------------------------------------------------")
    if actual_eta == expected_eta:
        print(f"✅ PASS - ETA correctly calculated as {actual_eta}")
        return True
    else:
        print(f"❌ FAIL - ETA should be {expected_eta}, but got {actual_eta}")
        
        # Check if it's the specific bug (01:00 AM)
        if actual_eta == "01:00":
            print("🐛 This is the exact bug reported - AI returned 01:00 AM instead of 13:39 PM!")
            print("   This is a 12+ hour error in ETA calculation.")
        
        return False

if __name__ == "__main__":
    success = test_eta_60min_bug()
    if not success:
        sys.exit(1)
    else:
        print("\n✅ Test completed successfully!")
