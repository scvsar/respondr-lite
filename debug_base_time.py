"""
Test if the issue is related to base time minutes
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

def test_base_time_minutes():
    """Test if the issue is related to base time minutes"""
    
    base_times = [
        datetime(2025, 8, 11, 13, 0, 0),   # 13:00 - round hour
        datetime(2025, 8, 11, 13, 10, 0),  # 13:10 
        datetime(2025, 8, 11, 13, 13, 0),  # 13:13 (no seconds)
        datetime(2025, 8, 11, 13, 13, 15), # 13:13:15 (with seconds)
        datetime(2025, 8, 11, 13, 30, 0),  # 13:30
    ]
    
    print("="*70)
    print("BASE TIME MINUTES TEST - 90MIN ETA")
    print("="*70)
    
    for base_time in base_times:
        expected_eta = base_time.replace(second=0, microsecond=0) + timedelta(minutes=90)
        expected_str = expected_eta.strftime("%H:%M")
        
        message = "Sender: Test User. Message: SAR-1 ETA 90min"
        
        try:
            result = extract_details_from_text(message, base_time=base_time)
            actual_eta = result.get('eta', 'Unknown')
            
            status = "✅" if actual_eta == expected_str else "❌"
            print(f"{status} Base: {base_time.strftime('%H:%M:%S')} → Expected: {expected_str}, Got: {actual_eta}")
            
        except Exception as e:
            print(f"❌ Base: {base_time.strftime('%H:%M:%S')} → Error: {e}")

if __name__ == "__main__":
    from datetime import timedelta
    test_base_time_minutes()
