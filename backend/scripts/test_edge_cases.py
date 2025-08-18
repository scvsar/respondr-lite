#!/usr/bin/env python3
import requests
import json

# More ambiguous test cases that might show mode differences
test_cases = [
    'on my way in the tanker truck',  # Should test vehicle extraction without SAR prefix
    'responding in about an hour',     # Vague ETA that might be parsed differently  
    'delayed - technical difficulties', # Edge case status
    'taking command 1',               # Ambiguous - command vehicle or SAR-1?
    'might be 30 mins late',          # Complex ETA language
    'status?',                        # Query vs status
    'copy that, en route',            # Professional response
    'available now for calls',        # Availability vs response
    'heading back to station',        # Return vs respond
    'SAR 23 and 45 responding together' # Multiple vehicles
]

def main():
    print('=== Advanced Mode Comparison Tests ===')
    print('Testing edge cases for mode differences...\n')

    for i, text in enumerate(test_cases, 1):
        print(f'[Test {i}] "{text}"')
        try:
            resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': text})
            if resp.status_code != 200:
                print(f'  ERROR: HTTP {resp.status_code} - {resp.text[:100]}')
                continue
                
            data = resp.json()
            
            # New LLM-only parse-debug only returns llm_only
            llm_only = data.get('llm_only', {})
            print(f'  LLM-only: vehicle={llm_only.get("vehicle")} eta={llm_only.get("eta")} status={llm_only.get("raw_status")}')
            print()
                
        except Exception as e:
            print(f'  ERROR: {e}\n')

    # Test direct LLM call with inspection
    print('\n=== Direct LLM Inspection ===')
    test_text = 'on my way in the tanker truck'
    print(f'Testing: "{test_text}"')

    try:
        resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': test_text})
        if resp.status_code == 200:
            data = resp.json()
            if 'llm_debug' in data:
                print('LLM Debug Info:')
                print(json.dumps(data['llm_debug'], indent=2))
            else:
                print('No LLM debug info available')
        else:
            print(f'Error: {resp.status_code} - {resp.text}')
    except Exception as e:
        print(f'Error: {e}')


if __name__ == "__main__":
    main()
