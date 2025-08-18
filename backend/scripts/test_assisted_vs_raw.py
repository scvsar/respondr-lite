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

def main():
    print('=== Testing Raw vs Assisted Mode Differences ===')

    for i, text in enumerate(test_cases, 1):
        print(f'\n[Test {i}] "{text}"')
        
        try:
            resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': text})
            if resp.status_code != 200:
                print(f'  ERROR: {resp.status_code} - {resp.text}')
                continue
                
            data = resp.json()
            # LLM-only endpoint now
            llm_only = data.get('llm_only', {})
            print(f'  LLM-only: vehicle="{llm_only.get("vehicle")}" eta="{llm_only.get("eta")}" status="{llm_only.get("raw_status")}"')
            
        except Exception as e:
            print(f'  ERROR: {e}')

    print('\n=== LLM Availability Check ===')
    try:
        resp = requests.post('http://localhost:8000/api/parse-debug', json={'text': 'test'})
        if resp.status_code == 200:
            data = resp.json()
            print(f'LLM-only available: {data.get("llm_only_available")}')
            print(f'Default mode: {data.get("env_default_mode")}')
    except Exception as e:
        print(f'Error checking availability: {e}')


if __name__ == "__main__":
    main()