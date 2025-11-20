#!/usr/bin/env python3
"""
Script to list local users for the Respondr application.
"""

import sys
import os
import asyncio
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Set required environment variables for local auth
os.environ["ENABLE_LOCAL_AUTH"] = "true"
os.environ["PYTEST_CURRENT_TEST"] = "true"  # Enable testing mode to bypass some checks

from app.local_auth import list_local_users
from app.config import LOCAL_USERS_TABLE

async def main():
    print(f"Listing users from table: {LOCAL_USERS_TABLE}")
    print("-" * 90)
    print(f"{'Username':<15} {'Display Name':<25} {'Email':<25} {'Admin':<6} {'Org':<15}")
    print("-" * 90)

    try:
        users = await list_local_users()
        if not users:
            print("No local users found.")
            return

        for user in users:
            print(f"{user.username:<15} {user.display_name:<25} {user.email:<25} {str(user.is_admin):<6} {user.organization:<15}")
        
        print("-" * 90)
        print(f"Total users: {len(users)}")

    except Exception as e:
        print(f"❌ Error listing users: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
