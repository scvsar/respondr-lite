"""
Test multiple minute values to understand the AI parsing pattern
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

def test_multiple_minutes():
    """Test various minute values to understand the pattern"""
    
    test_time = datetime(2025, 8, 11, 13, 0, 0)  # Use clean 13:00 for easier math
    
    test_cases = [
        ("60min", "14:00"),   # 13:00 + 60min = 14:00
        ("90min", "14:30"),   # 13:00 + 90min = 14:30  
        ("120min", "15:00"),  # 13:00 + 120min = 15:00
        ("75min", "14:15"),   # 13:00 + 75min = 14:15
        ("45min", "13:45"),   # 13:00 + 45min = 13:45
    ]
    
    print("="*70)
    print("MULTIPLE MINUTE VALUES TEST")
    print("="*70)
    print(f"Base time: {test_time.strftime('%H:%M')}")
    print()
    
    for minute_text, expected_eta in test_cases:
        message = f"Sender: Test User. Message: SAR-1 ETA {minute_text}"
        
        try:
            result = extract_details_from_text(message, base_time=test_time)
            actual_eta = result.get('eta', 'Unknown')
            
            status = "✅" if actual_eta == expected_eta else "❌"
            print(f"{status} {minute_text:>8} → Expected: {expected_eta}, Got: {actual_eta}")
            
        except Exception as e:
            print(f"❌ {minute_text:>8} → Error: {e}")
    
    print()
    print("Pattern Analysis:")
    print("Looking for systematic errors in minute calculations...")

if __name__ == "__main__":
    test_multiple_minutes()
