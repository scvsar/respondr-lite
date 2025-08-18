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
        
        raw = data['raw']
        assisted = data['assisted'] 
        llm_only = data['llm_only']
        
        print(f'  Raw:      vehicle={raw["vehicle"]:15} eta={raw["eta"]:15} status={raw["raw_status"]}')
        print(f'  Assisted: vehicle={assisted["vehicle"]:15} eta={assisted["eta"]:15} status={assisted["raw_status"]}') 
        print(f'  LLM-only: vehicle={llm_only["vehicle"]:15} eta={llm_only["eta"]:15} status={llm_only["raw_status"]}')
        
        # Check for any differences
        fields_match = []
        fields_match.append(raw["vehicle"] == assisted["vehicle"] == llm_only["vehicle"])
        fields_match.append(raw["eta"] == assisted["eta"] == llm_only["eta"])
        fields_match.append(raw["raw_status"] == assisted["raw_status"] == llm_only["raw_status"])
        
        if all(fields_match):
            print('  → All modes IDENTICAL')
        else:
            print('  → *** DIFFERENCES detected! ***')
            if not fields_match[0]:
                print(f'      Vehicle differs: raw="{raw["vehicle"]}" assisted="{assisted["vehicle"]}" llm="{llm_only["vehicle"]}"')
            if not fields_match[1]:
                print(f'      ETA differs: raw="{raw["eta"]}" assisted="{assisted["eta"]}" llm="{llm_only["eta"]}"')
            if not fields_match[2]:
                print(f'      Status differs: raw="{raw["raw_status"]}" assisted="{assisted["raw_status"]}" llm="{llm_only["raw_status"]}"')
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