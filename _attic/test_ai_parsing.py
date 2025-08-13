"""
Test suite for AI message parsing validation
This validates the AI parsing against real SAR message data
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

# Fixed test time for consistent relative time calculations
TEST_BASE_TIME = datetime(2025, 8, 11, 9, 0, 0)  # 09:00 on test day

# Test data with real messages and expected outputs
TEST_MESSAGES = [
    # Responding messages
    {
        "message": "SAR-3 eta 8:30",
        "expected": {"vehicle": "SAR-3", "eta": "08:30"},
        "category": "responding"
    },
    {
        "message": "SAR-3 ETA 1545",
        "expected": {"vehicle": "SAR-3", "eta": "15:45"},
        "category": "responding"
    },
    {
        "message": "Responding sar78 1150",
        "expected": {"vehicle": "SAR-78", "eta": "11:50"},
        "category": "responding"
    },
    {
        "message": "POV ETA 0830",
        "expected": {"vehicle": "POV", "eta": "08:30"},
        "category": "responding"
    },
    {
        "message": "Responding POV eta 830",
        "expected": {"vehicle": "POV", "eta": "08:30"},
        "category": "responding"
    },
    {
        "message": "Responding with SAR-12, Eta 0900",
        "expected": {"vehicle": "SAR-12", "eta": "09:00"},
        "category": "responding"
    },
    {
        "message": "Updated eta: arriving 11:30",
        "expected": {"vehicle": "Unknown", "eta": "11:30"},
        "category": "responding"
    },
    {
        "message": "Responding now. ETA 9:15. Will arrive at field or CP depending on current status",
        "expected": {"vehicle": "Unknown", "eta": "09:15"},
        "category": "responding"
    },
    {
        "message": "Responding with SAR-2. ETA 9:00",
        "expected": {"vehicle": "SAR-2", "eta": "09:00"},
        "category": "responding"
    },
    {
        "message": "POV eta 845",
        "expected": {"vehicle": "POV", "eta": "08:45"},
        "category": "responding"
    },
    {
        "message": "SAR-5 9:00",
        "expected": {"vehicle": "SAR-5", "eta": "09:00"},
        "category": "responding"
    },
    {
        "message": "Responding SAR-60 ETA 9:30",
        "expected": {"vehicle": "SAR-60", "eta": "09:30"},
        "category": "responding"
    },
    {
        "message": "Responding pov eta be there in 20",
        "expected": {"vehicle": "POV", "eta": "09:20"},  # 09:00 + 20 mins = 09:20
        "category": "responding"
    },
    {
        "message": "SAR-1 heading there",
        "expected": {"vehicle": "SAR-1", "eta": "Unknown"},
        "category": "responding"
    },
    {
        "message": "SAR-12 avail for CP",
        "expected": {"vehicle": "SAR-12", "eta": "Unknown"},
        "category": "responding"
    },
    {
        "message": "ETA 30 mins",
        "expected": {"vehicle": "Unknown", "eta": "09:30"},  # 09:00 + 30 mins = 09:30
        "category": "responding"
    },
    {
        "message": "I can respond as IMT",
        "expected": {"vehicle": "Unknown", "eta": "Unknown"},
        "category": "responding"
    },
    {
        "message": "ETA 15 mins or so",
        "expected": {"vehicle": "Unknown", "eta": "09:15"},  # 09:00 + 15 mins = 09:15
        "category": "responding"
    },
    {
        "message": "I can respond. ETA 6-7 minutes",
        "expected": {"vehicle": "Unknown", "eta": "09:07"},  # 09:00 + 7 mins = 09:07
        "category": "responding"
    },
    {
        "message": "Responding SAR7 ETA 60min",
        "expected": {"vehicle": "SAR-7", "eta": "10:00"},  # 09:00 + 60 mins = 10:00
        "category": "responding"
    },
    {
        "message": "Responding but presumably to field",
        "expected": {"vehicle": "Unknown", "eta": "Unknown"},
        "category": "responding"
    },
    {
        "message": "My eta is 0900 as well",
        "expected": {"vehicle": "Unknown", "eta": "09:00"},
        "category": "responding"
    },
    {
        "message": "Responding",
        "expected": {"vehicle": "Unknown", "eta": "Unknown"},
        "category": "responding"
    },
    
    # Cancellation/Stand-down messages
    {
        "message": "can't make it, sorry",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "Can't make it today, sorry",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "Ok I can't make it",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "Ok I can't make it now",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "I also can't make it",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "I also can't make it now",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "Sorry, backing out",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "1022",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "10-22",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "Copied 10-22",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "Mission canceled. Subject found",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "Who can respond to Vesper mission?",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    },
    {
        "message": "Key for 74 is in the key box",
        "expected": {"vehicle": "Not Responding", "eta": "Cancelled"},
        "category": "cancelled"
    }
]

def test_ai_parsing():
    """Test the AI parsing against expected results"""
    
    # Check if we have the required environment variables
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    
    if not all([api_key, endpoint, deployment, api_version]):
        print("=" * 80)
        print("SKIPPING AI PARSING TEST - MISSING AZURE OPENAI CREDENTIALS")
        print("=" * 80)
        print("Required environment variables:")
        print(f"  AZURE_OPENAI_API_KEY: {'✓' if api_key else '✗'}")
        print(f"  AZURE_OPENAI_ENDPOINT: {'✓' if endpoint else '✗'}")
        print(f"  AZURE_OPENAI_DEPLOYMENT: {'✓' if deployment else '✗'}")
        print(f"  AZURE_OPENAI_API_VERSION: {'✓' if api_version else '✗'}")
        print("\nPlease set these environment variables in your .env file to run this test.")
        print("Alternatively, run 'python test_ai_parsing_mock.py' for mock testing.")
        return 0, 0, []
    
    print("=" * 80)
    print("AI PARSING VALIDATION TEST")
    print("=" * 80)
    print(f"Using Azure OpenAI endpoint: {endpoint}")
    print(f"Using deployment: {deployment}")
    
    total_tests = len(TEST_MESSAGES)
    passed_tests = 0
    failed_tests = []
    
    for i, test_case in enumerate(TEST_MESSAGES, 1):
        message = test_case["message"]
        expected = test_case["expected"].copy()
        category = test_case["category"]
        
        print(f"\nTest {i}/{total_tests}: {category.upper()}")
        print(f"Message: '{message}'")
        print(f"Expected: {expected}")
        
        try:
            # Call the actual function with fixed test time
            result = extract_details_from_text(message, TEST_BASE_TIME)
            print(f"Actual:   {result}")
            
            # Check if the result matches expected
            if result == expected:
                print("PASS")
                passed_tests += 1
            else:
                print("FAIL")
                failed_tests.append({
                    "test_number": i,
                    "message": message,
                    "expected": expected,
                    "actual": result,
                    "category": category
                })
        except Exception as e:
            print(f"ERROR: {str(e)}")
            failed_tests.append({
                "test_number": i,
                "message": message,
                "expected": expected,
                "actual": f"ERROR: {str(e)}",
                "category": category
            })
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {len(failed_tests)}")
    print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
    
    if failed_tests:
        print("\n" + "=" * 80)
        print("FAILED TESTS DETAILS")
        print("=" * 80)
        
        # Group failures by category
        responding_failures = [f for f in failed_tests if f["category"] == "responding"]
        cancelled_failures = [f for f in failed_tests if f["category"] == "cancelled"]
        
        if responding_failures:
            print(f"\nRESPONDING MESSAGE FAILURES ({len(responding_failures)}):")
            for failure in responding_failures:
                print(f"\nTest {failure['test_number']}: '{failure['message']}'")
                print(f"  Expected: {failure['expected']}")
                print(f"  Actual:   {failure['actual']}")
        
        if cancelled_failures:
            print(f"\nCANCELLATION MESSAGE FAILURES ({len(cancelled_failures)}):")
            for failure in cancelled_failures:
                print(f"\nTest {failure['test_number']}: '{failure['message']}'")
                print(f"  Expected: {failure['expected']}")
                print(f"  Actual:   {failure['actual']}")
    
    return passed_tests, len(failed_tests), failed_tests

if __name__ == "__main__":
    # Run the test
    passed, failed, failures = test_ai_parsing()
    
    # Exit with error code if tests failed
    if failed > 0:
        exit(1)
    else:
        print("\nAll tests passed!")
        exit(0)
