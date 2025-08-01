#!/usr/bin/env python3
"""
Run all pytest tests for the Respondr backend
"""
import os
import sys
import subprocess

def main():
    """Run all pytest tests"""
    print("Running Respondr backend tests...")
    
    # Use subprocess for better compatibility
    # Add coverage and verbose flags
    cmd = [
        "pytest",
        "-v",  # Verbose
        "--cov=.",  # Coverage for all files
        "--cov-report=term",  # Show coverage in terminal
        "test_main.py"  # Main test file
    ]
    
    # Run the tests
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Print the output
    print(result.stdout)
    if result.stderr:
        print("Errors:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
    
    # Return exit code
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
