#!/usr/bin/env python3
import requests
import json

# Test a case that should definitely show differences
test_text = "Rolling out in command truck 99, ETA 2 hours"
print(f'Testing: "{test_text}"')

try:
    resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': test_text})
    print(f'Status: {resp.status_code}')
    
    if resp.status_code == 200:
        data = resp.json()
        
        print('\nRaw mode:')
        print(json.dumps(data['raw'], indent=2))
        
        print('\nAssisted mode:')
        print(json.dumps(data['assisted'], indent=2))
        
        print('\nLLM-only mode:')
        print(json.dumps(data['llm_only'], indent=2))
        
        # Check for differences
        raw = data['raw']
        assisted = data['assisted'] 
        llm_only = data['llm_only']
        
        print('\n=== COMPARISON ===')
        print(f'Raw:      vehicle="{raw["vehicle"]}" eta="{raw["eta"]}" status="{raw["raw_status"]}"')
        print(f'Assisted: vehicle="{assisted["vehicle"]}" eta="{assisted["eta"]}" status="{assisted["raw_status"]}"') 
        print(f'LLM-only: vehicle="{llm_only["vehicle"]}" eta="{llm_only["eta"]}" status="{llm_only["raw_status"]}"')
        
        # Specifically check each field
        fields_differ = []
        if raw["vehicle"] != assisted["vehicle"] or raw["vehicle"] != llm_only["vehicle"] or assisted["vehicle"] != llm_only["vehicle"]:
            fields_differ.append("vehicle")
        if raw["eta"] != assisted["eta"] or raw["eta"] != llm_only["eta"] or assisted["eta"] != llm_only["eta"]:
            fields_differ.append("eta")
        if raw["raw_status"] != assisted["raw_status"] or raw["raw_status"] != llm_only["raw_status"] or assisted["raw_status"] != llm_only["raw_status"]:
            fields_differ.append("status")
            
        if fields_differ:
            print(f'\n*** DIFFERENCES FOUND in: {", ".join(fields_differ)} ***')
        else:
            print('\n→ All modes produce IDENTICAL results')
            
    else:
        print(f'Error: {resp.text}')
        
except Exception as e:
    print(f'Error: {e}')