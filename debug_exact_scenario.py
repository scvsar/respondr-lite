"""
Test the exact failing scenario
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv('backend/.env')

# Add backend directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_path = os.path.join(current_dir, 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

try:
    from main import extract_details_from_text
except ImportError as e:
    print(f"Error importing: {e}")
    sys.exit(1)

def test_exact_failing_scenario():
    """Test the exact scenario that failed"""
    
    # Use the exact same time and message format that failed
    test_time = datetime(2025, 8, 11, 13, 13, 15)
    
    test_cases = [
        ("Sender: 90min Test User. Message: Responding POV ETA 90min", "14:43"),
        ("Sender: Test User. Message: SAR-1 ETA 90min", "14:43"),
        ("Sender: 90min Test User. Message: POV ETA 90min", "14:43"),
        ("Sender: 90min Test User. Message: ETA 90min", "14:43"),
    ]
    
    print("="*70)
    print("EXACT FAILING SCENARIO TEST")
    print("="*70)
    print(f"Base time: {test_time.strftime('%H:%M:%S')}")
    print(f"Expected result: 13:13 + 90min = 14:43")
    print()
    
    for message, expected_eta in test_cases:
        try:
            result = extract_details_from_text(message, base_time=test_time)
            actual_eta = result.get('eta', 'Unknown')
            
            status = "✅" if actual_eta == expected_eta else "❌"
            print(f"{status} {actual_eta}")
            print(f"   Message: {message}")
            print(f"   Result: {result}")
            print()
            
        except Exception as e:
            print(f"❌ Error: {e}")
            print(f"   Message: {message}")
            print()

if __name__ == "__main__":
    test_exact_failing_scenario()
