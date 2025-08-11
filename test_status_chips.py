"""
Test script to verify new status chip functionality
This tests the enhanced status system with Available and Informational statuses
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

# Import the function we want to test
try:
    from main import extract_details_from_text
except ImportError as e:
    print(f"Error: Could not import extract_details_from_text from main.py: {e}")
    sys.exit(1)

# Fixed test time for consistent results
TEST_BASE_TIME = datetime(2025, 8, 11, 9, 0, 0)  # 09:00 on test day

# Test cases for new status types
TEST_CASES = [
    {
        "message": "I can respond as IMT",
        "expected_status": "Available",
        "description": "Available status test"
    },
    {
        "message": "Key for 74 is in the key box",
        "expected_status": "Informational", 
        "description": "Informational status test"
    },
    {
        "message": "Who can respond to this mission?",
        "expected_status": "Informational",
        "description": "Question/informational test"
    },
    {
        "message": "SAR-3 responding ETA 09:30",
        "expected_status": "Responding",
        "description": "Standard responding test"
    },
    {
        "message": "can't make it, sorry",
        "expected_status": "Cancelled",
        "description": "Cancelled status test"
    }
]

def test_status_chips():
    """Test the new status chip functionality"""
    
    print("=" * 60)
    print("STATUS CHIPS ENHANCEMENT TEST")
    print("=" * 60)
    print("Testing new Available and Informational status types...")
    print()
    
    passed = 0
    failed = 0
    
    for i, test_case in enumerate(TEST_CASES, 1):
        message = test_case["message"]
        expected_status = test_case["expected_status"]
        description = test_case["description"]
        
        print(f"Test {i}: {description}")
        print(f"Message: '{message}'")
        print(f"Expected Status: {expected_status}")
        
        try:
            # Call the AI parsing function
            result = extract_details_from_text(message, TEST_BASE_TIME)
            
            # Check if we got a raw_status (new format)
            raw_status = result.get("raw_status")
            if raw_status:
                print(f"AI Status: {raw_status}")
                
                # Map AI status to frontend status
                status_mapping = {
                    "Responding": "Responding",
                    "Available": "Available", 
                    "Informational": "Informational",
                    "Cancelled": "Cancelled",
                    "Unknown": "Unknown"
                }
                
                frontend_status = status_mapping.get(raw_status, "Unknown")
                print(f"Frontend Status: {frontend_status}")
                
                if frontend_status == expected_status:
                    print("✅ PASS")
                    passed += 1
                else:
                    print("❌ FAIL")
                    failed += 1
            else:
                # Fallback to legacy format
                vehicle = result.get("vehicle", "Unknown")
                eta = result.get("eta", "Unknown")
                
                if eta == "Cancelled":
                    frontend_status = "Cancelled"
                elif vehicle == "Not Responding":
                    frontend_status = "Not Responding"
                elif vehicle == "Unknown" and eta == "Unknown":
                    frontend_status = "Unknown"
                else:
                    frontend_status = "Responding"
                    
                print(f"Legacy Status: {frontend_status}")
                
                if frontend_status == expected_status:
                    print("✅ PASS")
                    passed += 1
                else:
                    print("❌ FAIL")
                    failed += 1
                    
        except Exception as e:
            print(f"❌ ERROR: {e}")
            failed += 1
            
        print()
    
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total Tests: {len(TEST_CASES)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success Rate: {(passed/len(TEST_CASES)*100):.1f}%")
    
    if passed == len(TEST_CASES):
        print("\n🎉 All tests passed! Status chips enhancement is working!")
    else:
        print(f"\n⚠️  {failed} test(s) failed. Review the results above.")

if __name__ == "__main__":
    test_status_chips()
