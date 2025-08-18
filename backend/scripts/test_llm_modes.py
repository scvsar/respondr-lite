#!/usr/bin/env python3
import requests
import json

# Test cases that should definitely show LLM differences
test_cases = [
    "maybe responding later",           # Ambiguous status
    "truck broke down, can't make it",  # Clear cancellation with slang
    "taking the big rig",              # Vehicle without SAR number
    "might be 30 minutes late",        # Complex ETA language
    "copy that, en route"              # Professional response
]

print('=== Detailed LLM Mode Testing ===')

for i, text in enumerate(test_cases, 1):
    print(f'\n[Test {i}] "{text}"')
    
    # Test direct webhook calls with explicit modes
    for mode in ['raw', 'assisted', 'llm-only']:
        try:
            resp = requests.post(f'http://localhost:8000/webhook?mode={mode}', json={'text': text})
            if resp.status_code == 200:
                print(f'  {mode:10}: ✓ OK')
            else:
                print(f'  {mode:10}: ✗ Error {resp.status_code}')
        except Exception as e:
            print(f'  {mode:10}: ✗ {e}')
    
    # Test parse-debug for detailed comparison
    try:
        resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': text})
        if resp.status_code == 200:
            data = resp.json()
            llm_only = data.get('llm_only', {})
            source = llm_only.get('status_source', 'Unknown')
            if source == 'LLM-Only':
                print(f'  DEBUG: LLM-only mode is working! Source: {source}')
            else:
                print(f'  DEBUG: LLM-only fallback to: {source}')
        else:
            print(f'  DEBUG: Parse-debug error: {resp.status_code}')
    except Exception as e:
        print(f'  DEBUG: {e}')