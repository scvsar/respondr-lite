#!/usr/bin/env python3
import requests
import json

# Test cases that should show differences between modes
test_cases = [
    'Taking SAR-42, ETA 15 minutes',
    'fuck this I\'m out', 
    'POV responding, see you at 21:15',
    'coming in 5',
    'maybe later',
    'key for 74 is in the box',
    '10-22',
    'Rolling now in 12, ETA 45 min'
]

print('=== Mode Comparison Tests ===')
print('Testing if raw/assisted/llm-only produce different outputs...\n')

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
        
        print(f'  Raw:      vehicle={raw["vehicle"]:10} eta={raw["eta"]:12} status={raw["raw_status"]}')
        print(f'  Assisted: vehicle={assisted["vehicle"]:10} eta={assisted["eta"]:12} status={assisted["raw_status"]}') 
        print(f'  LLM-only: vehicle={llm_only["vehicle"]:10} eta={llm_only["eta"]:12} status={llm_only["raw_status"]}')
        
        # Check for differences
        same_vehicle = raw["vehicle"] == assisted["vehicle"] == llm_only["vehicle"]
        same_eta = raw["eta"] == assisted["eta"] == llm_only["eta"] 
        same_status = raw["raw_status"] == assisted["raw_status"] == llm_only["raw_status"]
        
        if same_vehicle and same_eta and same_status:
            print('  → All modes IDENTICAL')
        else:
            print('  → DIFFERENCES detected ✓')
        print()
            
    except Exception as e:
        print(f'  ERROR: {e}\n')

# Final status check
try:
    resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': 'test'})
    if resp.status_code == 200:
        data = resp.json()
        print(f'\nLLM availability: assisted={data.get("assisted_available")}, llm_only={data.get("llm_only_available")}')
        print(f'Default mode: {data.get("env_default_mode")}')
except:
    print('\nCould not get LLM availability info')