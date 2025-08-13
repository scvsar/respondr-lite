"""
Analyze preprod webhook test results from saved JSON file
"""

import json
from datetime import datetime

def analyze_preprod_messages():
    """Analyze the messages from preprod Redis"""
    print("================================================================================")
    print("PREPROD WEBHOOK TEST RESULTS ANALYSIS")
    print("================================================================================")
    
    try:
        # Read the saved messages
        with open('preprod_messages.json', 'r', encoding='utf-8') as f:
            messages_json = f.read().strip()
        
        if not messages_json or messages_json == '(nil)':
            print("❌ No messages found in preprod Redis")
            return
            
        messages = json.loads(messages_json)
        print(f"📊 Found {len(messages)} total messages in preprod")
        
        # Filter for our test group
        test_group = "102193274"
        test_messages = [msg for msg in messages if msg.get('group_id') == test_group]
        
        if not test_messages:
            print(f"❌ No messages found for test group {test_group}")
            return
            
        print(f"🔍 Found {len(test_messages)} messages in test group {test_group}")
        
        # Look for our specific test messages
        test_cases = [
            ("Responding SAR7 ETA 60min", "Randy Treit"),
            ("ETA 30 minutes", "Test User"),
            ("SAR-5 ETA 45min", "Test User"), 
            ("SAR-3 eta 8:30", "Test User"),
            ("POV ETA 0830", "Test User"),
            ("can't make it, sorry", "Test User"),
            ("10-22", "Test User")
        ]
        
        found_tests = []
        for msg in test_messages:
            text = msg.get('text', '')
            name = msg.get('name', '')
            
            for test_text, test_name in test_cases:
                if test_text in text and name == test_name:
                    found_tests.append(msg)
                    break
        
        if not found_tests:
            print("❌ No test messages found")
            print("Recent messages in test group:")
            for msg in test_messages[-5:]:
                print(f"  - {msg.get('name')}: '{msg.get('text', '')[:50]}...'")
            return
            
        print(f"🎯 Found {len(found_tests)} test case results")
        print("="*80)
        
        # Analyze each test case
        for i, msg in enumerate(found_tests, 1):
            print(f"\nTest Case {i}: {msg.get('name', 'Unknown')}")
            print(f"  Text: '{msg.get('text', '')}'")
            print(f"  Vehicle: {msg.get('vehicle', 'Unknown')}")
            print(f"  ETA: {msg.get('eta', 'Unknown')}")
            print(f"  Raw Status: {msg.get('raw_status', 'N/A')}")
            print(f"  Arrival Status: {msg.get('arrival_status', 'Unknown')}")
            
            # Specific validations
            text = msg.get('text', '')
            eta = msg.get('eta', 'Unknown')
            vehicle = msg.get('vehicle', 'Unknown')
            raw_status = msg.get('raw_status', 'Unknown')
            arrival_status = msg.get('arrival_status', 'Unknown')
            
            if 'SAR7 ETA 60min' in text:
                print(f"  🎯 ORIGINAL BUG CASE VALIDATION:")
                if eta == "13:39":
                    print(f"     ✅ CORRECT - ETA is 13:39 (12:39 + 60min)")
                elif eta == "01:00":
                    print(f"     ❌ BUG STILL EXISTS - ETA is 01:00 AM (WRONG!)")
                else:
                    print(f"     ⚠️  UNEXPECTED - ETA is {eta} (expected 13:39)")
                    
                if vehicle == "SAR-7":
                    print(f"     ✅ Vehicle correctly parsed as SAR-7")
                else:
                    print(f"     ❌ Vehicle should be SAR-7, got {vehicle}")
                    
            elif 'ETA 30 minutes' in text:
                print(f"  📊 30min relative time test:")
                if eta == "14:45":
                    print(f"     ✅ CORRECT - ETA is 14:45 (14:15 + 30min)")
                else:
                    print(f"     ❌ Expected 14:45, got {eta}")
                    
            elif 'SAR-5 ETA 45min' in text:
                print(f"  📊 45min relative time test:")
                if eta == "19:15":
                    print(f"     ✅ CORRECT - ETA is 19:15 (18:30 + 45min)")
                else:
                    print(f"     ❌ Expected 19:15, got {eta}")
                    
            elif "can't make it" in text:
                print(f"  📊 Cancellation test:")
                if arrival_status == "Cancelled" or raw_status == "Cancelled":
                    print(f"     ✅ CORRECT - Status is Cancelled")
                else:
                    print(f"     ❌ Expected Cancelled status, got arrival:{arrival_status}, raw:{raw_status}")
                    
            elif "10-22" in text:
                print(f"  📊 10-22 cancellation test:")
                if arrival_status == "Cancelled" or raw_status == "Cancelled":
                    print(f"     ✅ CORRECT - Status is Cancelled")
                else:
                    print(f"     ❌ Expected Cancelled status, got arrival:{arrival_status}, raw:{raw_status}")
                    
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        print(f"✅ Successfully sent and processed {len(found_tests)} test cases")
        print("🔍 Key findings:")
        
        # Check for the main bug
        sar7_tests = [msg for msg in found_tests if 'SAR7 ETA 60min' in msg.get('text', '')]
        if sar7_tests:
            eta = sar7_tests[0].get('eta', 'Unknown')
            if eta == "13:39":
                print("   ✅ Original bug FIXED - SAR7 ETA 60min now correctly calculates 13:39")
            elif eta == "01:00":
                print("   ❌ Original bug PERSISTS - SAR7 ETA 60min still returns 01:00 AM")
            else:
                print(f"   ⚠️  Unexpected result for SAR7 ETA 60min: {eta}")
        
        print("\n🎉 End-to-end webhook testing completed!")
        
    except Exception as e:
        print(f"❌ Error analyzing preprod messages: {e}")
        print("Make sure preprod_messages.json exists and contains valid JSON data")

if __name__ == "__main__":
    analyze_preprod_messages()
