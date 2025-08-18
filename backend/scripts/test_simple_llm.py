#!/usr/bin/env python3
import requests
import json

# Simple test to see if LLM is working
test_text = "maybe responding later"
print(f'Testing: "{test_text}"')

try:
    resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': test_text})
    print(f'Status: {resp.status_code}')
    
    if resp.status_code == 200:
        data = resp.json()
        
        llm_only = data['llm_only']
        print(f'\nLLM-only result:')
        print(f'  Vehicle: {llm_only["vehicle"]}')
        print(f'  ETA: {llm_only["eta"]}')
        print(f'  Status: {llm_only["raw_status"]}')
        print(f'  Source: {llm_only["status_source"]}')
        print(f'  Confidence: {llm_only["status_confidence"]}')
        
        if llm_only["status_source"] == "LLM-Only":
            print('\n🎉 SUCCESS! LLM-only mode is working!')
        else:
            print(f'\n❌ Still falling back to: {llm_only["status_source"]}')
            
    else:
        print(f'Error: {resp.text}')
        
except Exception as e:
    print(f'Error: {e}')