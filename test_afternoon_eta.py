"""
Additional test case for the ETA 60min bug with specific timestamp
This ensures we catch regressions for afternoon ETA calculations
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

# Test cases with different afternoon timestamps
AFTERNOON_ETA_TESTS = [
    {
        "name": "Reported Bug Case - 12:39 PM",
        "base_time": datetime(2025, 8, 11, 12, 39, 15),  # 12:39 PM
        "message": "Responding SAR7 ETA 60min",
        "expected": {"vehicle": "SAR-7", "eta": "13:39"},  # Should be 13:39, not 01:00
    },
    {
        "name": "Afternoon 30min test",
        "base_time": datetime(2025, 8, 11, 14, 15, 0),   # 2:15 PM
        "message": "ETA 30 minutes",
        "expected": {"vehicle": "Unknown", "eta": "14:45"},  # Should be 14:45
    },
    {
        "name": "Evening test",
        "base_time": datetime(2025, 8, 11, 18, 30, 0),   # 6:30 PM
        "message": "SAR-5 ETA 45min",
        "expected": {"vehicle": "SAR-5", "eta": "19:15"},  # Should be 19:15
    },
]

def run_afternoon_eta_tests():
    """Run tests specifically for afternoon ETA calculations"""
    print("================================================================================")
    print("AFTERNOON ETA CALCULATION TESTS")
    print("================================================================================")
    
    total_tests = len(AFTERNOON_ETA_TESTS)
    passed_tests = 0
    failed_tests = []
    
    for i, test_case in enumerate(AFTERNOON_ETA_TESTS, 1):
        print(f"\nTest {i}/{total_tests}: {test_case['name']}")
        print(f"Base time: {test_case['base_time'].strftime('%H:%M')} ({test_case['base_time'].strftime('%I:%M %p')})")
        print(f"Message: '{test_case['message']}'")
        print(f"Expected: {test_case['expected']}")
        
        # Call AI parsing
        result = extract_details_from_text(test_case['message'], test_case['base_time'])
        
        # Check results
        vehicle_match = result.get('vehicle', 'Unknown') == test_case['expected']['vehicle']
        eta_match = result.get('eta', 'Unknown') == test_case['expected']['eta']
        
        if vehicle_match and eta_match:
            print(f"✅ PASS")
            passed_tests += 1
        else:
            print(f"❌ FAIL")
            print(f"   Expected: {test_case['expected']}")
            print(f"   Actual:   {{'vehicle': '{result.get('vehicle', 'Unknown')}', 'eta': '{result.get('eta', 'Unknown')}'}}")
            failed_tests.append(test_case['name'])
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {len(failed_tests)}")
    print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
    
    if failed_tests:
        print(f"\nFailed Tests:")
        for test_name in failed_tests:
            print(f"  - {test_name}")
        return False
    else:
        print("\n✅ All afternoon ETA tests passed!")
        return True

if __name__ == "__main__":
    success = run_afternoon_eta_tests()
    if not success:
        sys.exit(1)
