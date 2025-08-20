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
    
    tests_dir = os.path.join(os.path.dirname(__file__), "tests")

    # Use subprocess for better compatibility
    # Try to use coverage if available, otherwise run basic pytest
    try:
        import pytest_cov  # type: ignore  # noqa: F401
        cmd = [
            "pytest",
            "-v",  # Verbose
            "--cov=.",  # Coverage for all files
            "--cov-report=term",  # Show coverage in terminal
            tests_dir,
            "--ignore=tests/test_system.py",
            "--ignore=tests/test_preprod.py",
            "--ignore=tests/test_webhook.py",
        ]
    except ImportError:
        print("pytest-cov not available, running basic tests...")
        cmd = [
            "pytest",
            "-v",  # Verbose
            tests_dir,
            "--ignore=tests/test_system.py",
            "--ignore=tests/test_preprod.py",
            "--ignore=tests/test_webhook.py",
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
