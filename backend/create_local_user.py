#!/usr/bin/env python3
"""
Script to create local users for the Respondr application.
This is useful for creating deputy/external user accounts.

Usage:
    python create_local_user.py <username> <email> <display_name> [--admin] [--organization "Sheriff's Dept"]
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
os.environ["PYTEST_CURRENT_TEST"] = "true"  # Enable testing mode to bypass some checks

from app.local_auth import create_local_user, get_local_user
from app.config import LOCAL_USERS_TABLE


async def main():
    """Main function to create a local user."""
    if len(sys.argv) < 4:
        print("Usage: python create_local_user.py <username> <email> <display_name> [--admin] [--organization 'org']")
        print("\nExample:")
        print("  python create_local_user.py deputy1 deputy1@sheriff.org 'Deputy John Smith' --organization 'Sheriff Dept'")
        print("  python create_local_user.py admin admin@scvsar.org 'Admin User' --admin")
        sys.exit(1)
    
    username = sys.argv[1]
    email = sys.argv[2]
    display_name = sys.argv[3]
    
    # Parse optional arguments
    is_admin = "--admin" in sys.argv
    organization = ""
    
    if "--organization" in sys.argv:
        org_index = sys.argv.index("--organization")
        if org_index + 1 < len(sys.argv):
            organization = sys.argv[org_index + 1]
    
    print(f"Creating local user account:")
    print(f"  Username: {username}")
    print(f"  Email: {email}")
    print(f"  Display Name: {display_name}")
    print(f"  Organization: {organization or '(none)'}")
    print(f"  Admin: {'Yes' if is_admin else 'No'}")
    print(f"  Table: {LOCAL_USERS_TABLE}")
    print()
    
    # Check if user already exists
    existing = await get_local_user(username)
    if existing:
        print(f"❌ User '{username}' already exists!")
        sys.exit(1)
    
    # Get password securely
    password = getpass.getpass(f"Enter password for {username}: ")
    if not password:
        print("❌ Password cannot be empty!")
        sys.exit(1)
    
    confirm_password = getpass.getpass("Confirm password: ")
    if password != confirm_password:
        print("❌ Passwords do not match!")
        sys.exit(1)
    
    # Create the user
    try:
        success = await create_local_user(
            username=username,
            password=password,
            email=email,
            display_name=display_name,
            is_admin=is_admin,
            organization=organization
        )
        
        if success:
            print(f"✅ User '{username}' created successfully!")
            print(f"   They can now log in at the application login page.")
        else:
            print(f"❌ Failed to create user '{username}'")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Error creating user: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())