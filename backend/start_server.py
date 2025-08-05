#!/usr/bin/env python3
"""
Simple server startup script
"""
import uvicorn
import os
import sys

# Ensure we're in the right directory
os.chdir(os.path.dirname(__file__))

if __name__ == "__main__":
    print("🚀 Starting Respondr FastAPI server...")
    print(f"Working directory: {os.getcwd()}")
    print(f"Python path: {sys.path[0]}")
    
    try:
        # Import main to check if it works
        import main
        print("✅ Main module imported successfully")
        
        # Start the server
        uvicorn.run(
            "main:app", 
            host="127.0.0.1", 
            port=8000,
            log_level="info"
        )
    except Exception as e:
        print(f"❌ Error starting server: {e}")
        import traceback
        traceback.print_exc()
