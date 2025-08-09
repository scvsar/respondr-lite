#!/usr/bin/env python3
"""
Check the current environment status
"""
import requests

def check_environment():
    """Check the live environment configuration"""
    
    try:
        # Test the API status endpoint if it exists
        response = requests.get("http://localhost:8000/docs")
        if response.status_code == 200:
            print("✅ Backend is running")
        
        # Test basic API call
        api_response = requests.get("http://localhost:8000/api/responders")
        if api_response.status_code == 200:
            print("✅ API is responding")
            data = api_response.json()
            print(f"📊 Current responder count: {len(data)}")
        
    except Exception as e:
        print(f"❌ Error checking environment: {e}")

if __name__ == "__main__":
    check_environment()
