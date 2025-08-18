#!/usr/bin/env python3
import requests
import json

# Test cases that should trigger assisted LLM for different extraction
test_cases = [
    "maybe responding later",          # Ambiguous status
    "truck broke down, can't make it", # Clear cancellation  
    "rolling in the big rig",         # Vehicle without number
    "delayed by 30 minutes",          # ETA adjustment
    "on standby for calls"            # Availability status
]

print('=== Testing Raw vs Assisted Mode Differences ===')

for i, text in enumerate(test_cases, 1):
    print(f'\n[Test {i}] "{text}"')
    
    try:
        resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': text})
        if resp.status_code != 200:
            print(f'  ERROR: {resp.status_code} - {resp.text}')
            continue
            
        data = resp.json()
        raw = data['raw']
        assisted = data['assisted']
        
        print(f'  Raw:      vehicle="{raw["vehicle"]:12}" eta="{raw["eta"]:12}" status="{raw["raw_status"]:15}" source="{raw.get("status_source", "?")}"')
        print(f'  Assisted: vehicle="{assisted["vehicle"]:12}" eta="{assisted["eta"]:12}" status="{assisted["raw_status"]:15}" source="{assisted.get("status_source", "?")}"')
        
        # Check for differences between raw and assisted
        diff_found = False
        if raw["vehicle"] != assisted["vehicle"]:
            print(f'    → Vehicle differs: "{raw["vehicle"]}" vs "{assisted["vehicle"]}"')
            diff_found = True
        if raw["eta"] != assisted["eta"]:
            print(f'    → ETA differs: "{raw["eta"]}" vs "{assisted["eta"]}"')
            diff_found = True
        if raw["raw_status"] != assisted["raw_status"]:
            print(f'    → Status differs: "{raw["raw_status"]}" vs "{assisted["raw_status"]}"')
            diff_found = True
            
        if not diff_found:
            print('    → Raw and Assisted are IDENTICAL')
            
    except Exception as e:
        print(f'  ERROR: {e}')

print('\n=== LLM Availability Check ===')
try:
    resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': 'test'})
    if resp.status_code == 200:
        data = resp.json()
        print(f'Assisted available: {data.get("assisted_available")}')
        print(f'LLM-only available: {data.get("llm_only_available")}')
        print(f'Default mode: {data.get("env_default_mode")}')
except Exception as e:
    print(f'Error checking availability: {e}')