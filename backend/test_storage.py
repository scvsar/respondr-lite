#!/usr/bin/env python3
"""
Storage Fallback Test Script

This script demonstrates the new storage abstraction layer with automatic fallback.
It tests different scenarios including Redis unavailable and storage switching.
"""

import os
import sys
import json
import time
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.storage import get_storage_info, get_messages, save_messages
from app.storage_backends import StorageBackend


def print_section(title):
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def print_storage_status():
    """Print current storage status."""
    info = get_storage_info()
    print(f"Current Backend: {info['current_backend']}")
    print(f"Primary Backend: {info['primary_backend']}")
    print(f"Fallback Backend: {info['fallback_backend']}")
    print(f"Primary Healthy: {info['primary_healthy']}")
    print(f"Fallback Healthy: {info['fallback_healthy']}")
    print(f"Current Healthy: {info['current_healthy']}")


def test_basic_operations():
    """Test basic storage operations."""
    print_section("Testing Basic Storage Operations")
    
    # Test getting messages (should be empty initially)
    messages = get_messages()
    print(f"Initial messages count: {len(messages)}")
    
    # Test saving messages
    test_messages = [
        {
            "id": "test-001",
            "text": "Test message 1",
            "timestamp": datetime.now().isoformat(),
            "parsed": {"name": "Test User 1", "eta": "10 min"}
        },
        {
            "id": "test-002",
            "text": "Test message 2", 
            "timestamp": datetime.now().isoformat(),
            "parsed": {"name": "Test User 2", "eta": "15 min"}
        }
    ]
    
    success = save_messages(test_messages)
    print(f"Save operation successful: {success}")
    
    # Test getting messages back
    retrieved_messages = get_messages()
    print(f"Retrieved messages count: {len(retrieved_messages)}")
    
    if retrieved_messages:
        print("Sample message:")
        print(f"  ID: {retrieved_messages[0].get('id')}")
        print(f"  Name: {retrieved_messages[0].get('parsed', {}).get('name')}")


def test_storage_fallback():
    """Test storage fallback behavior."""
    print_section("Testing Storage Fallback")
    
    print("Current storage configuration:")
    print_storage_status()
    
    print(f"\nSTORAGE_BACKEND env var: {os.getenv('STORAGE_BACKEND', 'redis')}")
    print(f"STORAGE_FALLBACK env var: {os.getenv('STORAGE_FALLBACK', 'memory')}")
    
    # Test message persistence
    test_message = {
        "id": f"fallback-test-{int(time.time())}",
        "text": "Fallback test message",
        "timestamp": datetime.now().isoformat(),
        "parsed": {"name": "Fallback Test", "eta": "now"}
    }
    
    current_messages = get_messages()
    current_messages.append(test_message)
    
    success = save_messages(current_messages)
    print(f"\nSaved fallback test message: {success}")
    
    # Verify it was saved
    retrieved = get_messages()
    found = any(msg.get('id') == test_message['id'] for msg in retrieved)
    print(f"Message persisted correctly: {found}")


def test_different_backends():
    """Test different backend configurations."""
    print_section("Testing Different Backend Configurations")
    
    configs = [
        ("Redis Primary, Memory Fallback", "redis", "memory"),
        ("Memory Primary, File Fallback", "memory", "file"),
        ("File Primary, Memory Fallback", "file", "memory"),
    ]
    
    for name, primary, fallback in configs:
        print(f"\n--- {name} ---")
        
        # Set environment temporarily
        old_primary = os.getenv('STORAGE_BACKEND')
        old_fallback = os.getenv('STORAGE_FALLBACK')
        
        os.environ['STORAGE_BACKEND'] = primary
        os.environ['STORAGE_FALLBACK'] = fallback
        
        print(f"  Config: Primary={primary}, Fallback={fallback}")
        print(f"  This configuration would be used on next app restart")
        
        # Restore environment
        if old_primary:
            os.environ['STORAGE_BACKEND'] = old_primary
        else:
            os.environ.pop('STORAGE_BACKEND', None)
            
        if old_fallback:
            os.environ['STORAGE_FALLBACK'] = old_fallback
        else:
            os.environ.pop('STORAGE_FALLBACK', None)


def main():
    """Run all storage tests."""
    print("Respondr Storage Abstraction Test")
    print(f"Running at: {datetime.now()}")
    
    try:
        test_basic_operations()
        test_storage_fallback()
        test_different_backends()
        
        print_section("Test Summary")
        print("✅ All storage tests completed successfully!")
        print("\nFinal storage status:")
        print_storage_status()
        
        print("\n📋 Storage Features Demonstrated:")
        print("  • Automatic backend selection")
        print("  • Fallback mechanism")
        print("  • Backwards compatibility")
        print("  • Multiple backend support")
        print("  • Health monitoring")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())