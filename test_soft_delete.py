#!/usr/bin/env python3
"""
Test script for soft delete functionality
"""
import json
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from main import (
    messages, deleted_messages, 
    soft_delete_messages, undelete_messages,
    save_messages, save_deleted_messages,
    load_messages, load_deleted_messages
)

def test_soft_delete():
    """Test the soft delete functionality"""
    print("Testing soft delete functionality...")
    
    # Set testing mode to use in-memory storage
    import main
    main.is_testing = True
    
    # Clear any existing data
    messages.clear()
    deleted_messages.clear()
    
    # Create some test messages
    test_messages = [
        {"id": "test1", "name": "John Doe", "team": "Alpha", "text": "En route", "vehicle": "Unit 1"},
        {"id": "test2", "name": "Jane Smith", "team": "Bravo", "text": "On scene", "vehicle": "Unit 2"},
        {"id": "test3", "name": "Bob Johnson", "team": "Charlie", "text": "Delayed", "vehicle": "Unit 3"}
    ]
    
    # Add test messages
    messages.extend(test_messages)
    print(f"Added {len(messages)} test messages")
    
    # Test soft delete of one message
    to_delete = [msg for msg in messages if msg["id"] == "test2"]
    print(f"Soft deleting message: {to_delete[0]['name']}")
    soft_delete_messages(to_delete)
    
    # Remove from active messages
    messages[:] = [m for m in messages if m["id"] != "test2"]
    
    print(f"Active messages: {len(messages)}")
    print(f"Deleted messages: {len(deleted_messages)}")
    
    # Verify deleted message has timestamp
    deleted_msg = deleted_messages[0]
    print(f"Deleted message has timestamp: {'deleted_at' in deleted_msg}")
    print(f"Deleted at: {deleted_msg.get('deleted_at')}")
    
    # Test undelete
    print("\nTesting undelete...")
    restored_count = undelete_messages(["test2"])
    print(f"Restored {restored_count} messages")
    print(f"Active messages: {len(messages)}")
    print(f"Deleted messages: {len(deleted_messages)}")
    
    # Verify restored message doesn't have deleted_at timestamp
    restored_msg = [m for m in messages if m["id"] == "test2"][0]
    print(f"Restored message has no deleted_at: {'deleted_at' not in restored_msg}")
    
    print("\n✅ Soft delete test completed successfully!")

if __name__ == "__main__":
    test_soft_delete()
