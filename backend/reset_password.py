#!/usr/bin/env python3
"""
Script to reset a local user's password.
"""

import sys
import os
import asyncio
import getpass
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Set required environment variables for local auth
os.environ["ENABLE_LOCAL_AUTH"] = "true"
os.environ["PYTEST_CURRENT_TEST"] = "true"

from app.local_auth import update_local_user_password, get_local_user

async def main():
    if len(sys.argv) < 2:
        print("Usage: python reset_password.py <username> [--password <new_password>]")
        sys.exit(1)
    
    username = sys.argv[1]
    password = None
    
    if "--password" in sys.argv:
        try:
            idx = sys.argv.index("--password")
            password = sys.argv[idx + 1]
        except IndexError:
            print("Error: --password flag provided but no password specified.")
            sys.exit(1)

    print(f"Resetting password for user: {username}")
    
    # Check if user exists
    user = await get_local_user(username)
    if not user:
        print(f"❌ User '{username}' not found!")
        sys.exit(1)

    if not password:
        password = getpass.getpass(f"Enter new password for {username}: ")
        if not password:
            print("❌ Password cannot be empty!")
            sys.exit(1)
        
        confirm = getpass.getpass("Confirm new password: ")
        if password != confirm:
            print("❌ Passwords do not match!")
            sys.exit(1)
    
    success = await update_local_user_password(username, password)
    
    if success:
        print(f"✅ Password for '{username}' has been reset successfully.")
    else:
        print(f"❌ Failed to reset password for '{username}'.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
