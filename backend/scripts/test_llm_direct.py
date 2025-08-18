#!/usr/bin/env python3
import requests
import json

# Test with a very simple case to see if LLM is actually working
test_cases = [
    "SAR-99 responding",
    "test message",
    "hello world"
]

print('=== Testing LLM Direct Calls ===')

for i, text in enumerate(test_cases, 1):
    print(f'\n[Test {i}] "{text}"')
    
    # Try direct webhook call with llm-only mode  
    try:
        resp = requests.post('http://localhost:8000/webhook?mode=llm-only', json={'text': text})
        print(f'  Webhook response: {resp.status_code}')
        if resp.status_code == 200:
            data = resp.json()
            print(f'  Result: {json.dumps(data, indent=2)}')
        else:
            print(f'  Error: {resp.text[:200]}')
    except Exception as e:
        print(f'  Webhook error: {e}')
        
    # Also try parse-debug for comparison
    try:
        resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': text})
        if resp.status_code == 200:
            data = resp.json()
            llm_only = data.get('llm_only', {})
            print(f'  Parse-debug LLM-only: vehicle={llm_only.get("vehicle")}, status={llm_only.get("raw_status")}, source={llm_only.get("status_source")}')
        else:
            print(f'  Parse-debug error: {resp.status_code}')
    except Exception as e:
        print(f'  Parse-debug error: {e}')