"""
Direct test of the AI parsing function for 90min case
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

def test_90min_parsing():
    """Test the AI parsing directly for 90min case"""
    
    test_time = datetime(2025, 8, 11, 13, 13, 15)  # Match our webhook test time
    message = "Sender: 90min Test User. Message: Responding POV ETA 90min"
    
    print("="*60)
    print("DIRECT AI PARSING TEST - 90MIN")
    print("="*60)
    print(f"Test time: {test_time.strftime('%H:%M:%S')}")
    print(f"Message: {message}")
    print(f"Expected: eta should be calculated as 13:13 + 90min = 14:43")
    print()
    
    try:
        result = extract_details_from_text(message, base_time=test_time)
        print("AI Parsing Result:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        
        print()
        print("Analysis:")
        eta = result.get('eta', 'Unknown')
        if eta == '14:43':
            print("✅ CORRECT: AI calculated 90min correctly")
        elif eta == '13:03' or eta == '14:03':
            print("❌ BUG: AI miscalculated 90min")
        else:
            print(f"❓ UNEXPECTED: AI returned '{eta}'")
            
    except Exception as e:
        print(f"❌ Error during AI parsing: {e}")

if __name__ == "__main__":
    test_90min_parsing()
