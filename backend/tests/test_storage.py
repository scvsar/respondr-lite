"""
Test suite for storage layer functionality.

Tests the Redis-based storage system with in-memory fallback.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from app.storage import (
    get_messages, add_message, update_message, delete_message,
    get_deleted_messages, undelete_message, permanently_delete_message,
    clear_all_messages, clear_all_deleted_messages, bulk_delete_messages
)
from app.config import APP_TZ


class TestStorageOperations:
    """Test basic storage CRUD operations."""

    def test_add_and_get_message(self):
        """Test adding a message and retrieving it."""
        test_message = {
            "id": "test-message-1",
            "name": "Test User",
            "text": "Test message",
            "timestamp": datetime.now(APP_TZ).isoformat(),
            "vehicle": "POV",
            "eta": "15 minutes"
        }
        
        # Mock storage to use in-memory for testing
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                add_message(test_message)
                messages = get_messages()
                
                assert len(messages) == 1
                assert messages[0]["id"] == "test-message-1"
                assert messages[0]["name"] == "Test User"
                assert messages[0]["text"] == "Test message"

    def test_update_message(self):
        """Test updating an existing message."""
        test_message = {
            "id": "test-message-2",
            "name": "Test User",
            "text": "Original message",
            "vehicle": "POV"
        }
        
        updated_data = {
            "text": "Updated message",
            "vehicle": "SAR-78"
        }
        
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                add_message(test_message)
                update_message("test-message-2", updated_data)
                messages = get_messages()
                
                assert len(messages) == 1
                assert messages[0]["text"] == "Updated message"
                assert messages[0]["vehicle"] == "SAR-78"
                assert messages[0]["name"] == "Test User"  # Unchanged field

    def test_delete_message_soft_delete(self):
        """Test soft deleting a message."""
        test_message = {
            "id": "test-message-3",
            "name": "Test User",
            "text": "Message to delete"
        }
        
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                with patch('app.storage.deleted_messages_cache', []):
                    add_message(test_message)
                    delete_message("test-message-3")
                    
                    # Should not be in active messages
                    active_messages = get_messages()
                    assert len(active_messages) == 0
                    
                    # Should be in deleted messages
                    deleted_messages = get_deleted_messages()
                    assert len(deleted_messages) == 1
                    assert deleted_messages[0]["id"] == "test-message-3"

    def test_undelete_message(self):
        """Test restoring a deleted message."""
        test_message = {
            "id": "test-message-4",
            "name": "Test User",
            "text": "Message to undelete"
        }
        
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                with patch('app.storage.deleted_messages_cache', []):
                    add_message(test_message)
                    delete_message("test-message-4")
                    undelete_message("test-message-4")
                    
                    # Should be back in active messages
                    active_messages = get_messages()
                    assert len(active_messages) == 1
                    assert active_messages[0]["id"] == "test-message-4"
                    
                    # Should not be in deleted messages
                    deleted_messages = get_deleted_messages()
                    assert len(deleted_messages) == 0

    def test_permanently_delete_message(self):
        """Test permanently deleting a message."""
        test_message = {
            "id": "test-message-5",
            "name": "Test User",
            "text": "Message to permanently delete"
        }
        
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                with patch('app.storage.deleted_messages_cache', []):
                    add_message(test_message)
                    delete_message("test-message-5")
                    permanently_delete_message("test-message-5")
                    
                    # Should not be in active messages
                    active_messages = get_messages()
                    assert len(active_messages) == 0
                    
                    # Should not be in deleted messages
                    deleted_messages = get_deleted_messages()
                    assert len(deleted_messages) == 0

    def test_bulk_delete_messages(self):
        """Test bulk deleting multiple messages."""
        test_messages = [
            {"id": "bulk-1", "name": "User 1", "text": "Message 1"},
            {"id": "bulk-2", "name": "User 2", "text": "Message 2"},
            {"id": "bulk-3", "name": "User 3", "text": "Message 3"}
        ]
        
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                with patch('app.storage.deleted_messages_cache', []):
                    for msg in test_messages:
                        add_message(msg)
                    
                    bulk_delete_messages(["bulk-1", "bulk-3"])
                    
                    # Should have only one active message
                    active_messages = get_messages()
                    assert len(active_messages) == 1
                    assert active_messages[0]["id"] == "bulk-2"
                    
                    # Should have two deleted messages
                    deleted_messages = get_deleted_messages()
                    assert len(deleted_messages) == 2
                    deleted_ids = [msg["id"] for msg in deleted_messages]
                    assert "bulk-1" in deleted_ids
                    assert "bulk-3" in deleted_ids

    def test_clear_all_messages(self):
        """Test clearing all active messages."""
        test_messages = [
            {"id": "clear-1", "name": "User 1", "text": "Message 1"},
            {"id": "clear-2", "name": "User 2", "text": "Message 2"}
        ]
        
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                for msg in test_messages:
                    add_message(msg)
                
                clear_all_messages()
                
                messages = get_messages()
                assert len(messages) == 0

    def test_clear_all_deleted_messages(self):
        """Test clearing all deleted messages."""
        test_message = {
            "id": "clear-deleted-1",
            "name": "Test User",
            "text": "Message to clear"
        }
        
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                with patch('app.storage.deleted_messages_cache', []):
                    add_message(test_message)
                    delete_message("clear-deleted-1")
                    clear_all_deleted_messages()
                    
                    deleted_messages = get_deleted_messages()
                    assert len(deleted_messages) == 0


class TestRedisIntegration:
    """Test Redis client integration and fallback behavior."""

    def test_redis_client_connection_success(self):
        """Test successful Redis client connection."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = b'[]'  # Empty JSON array
        
        with patch('app.storage.redis_client', mock_redis):
            messages = get_messages()
            assert isinstance(messages, list)
            mock_redis.get.assert_called_once()

    def test_redis_client_connection_failure_fallback(self):
        """Test fallback to in-memory storage when Redis fails."""
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = Exception("Connection failed")
        
        with patch('app.storage.redis_client', mock_redis):
            with patch('app.storage.messages_cache', []):
                # Should fall back to in-memory storage
                messages = get_messages()
                assert isinstance(messages, list)
                assert len(messages) == 0

    def test_redis_data_serialization(self):
        """Test that data is properly serialized for Redis storage."""
        test_message = {
            "id": "redis-test-1",
            "name": "Test User",
            "text": "Test message",
            "timestamp": datetime.now(APP_TZ).isoformat()
        }
        
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = b'[]'
        
        with patch('app.storage.redis_client', mock_redis):
            add_message(test_message)
            
            # Should have called Redis set with JSON data
            mock_redis.set.assert_called()
            call_args = mock_redis.set.call_args
            assert 'messages' in call_args[0]  # Key
            # Value should be JSON serializable
            import json
            json.loads(call_args[0][1])  # Should not raise exception

    def test_redis_data_deserialization(self):
        """Test that data is properly deserialized from Redis storage."""
        test_data = [
            {
                "id": "redis-test-2",
                "name": "Test User",
                "text": "Test message"
            }
        ]
        
        import json
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = json.dumps(test_data).encode('utf-8')
        
        with patch('app.storage.redis_client', mock_redis):
            messages = get_messages()
            
            assert len(messages) == 1
            assert messages[0]["id"] == "redis-test-2"
            assert messages[0]["name"] == "Test User"


class TestStorageErrorHandling:
    """Test error handling in storage operations."""

    def test_add_message_with_missing_id(self):
        """Test adding message without ID generates one."""
        test_message = {
            "name": "Test User",
            "text": "Message without ID"
        }
        
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                add_message(test_message)
                messages = get_messages()
                
                assert len(messages) == 1
                assert "id" in messages[0]
                assert messages[0]["id"] is not None

    def test_update_nonexistent_message(self):
        """Test updating a message that doesn't exist."""
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                # Should not raise exception
                result = update_message("nonexistent-id", {"text": "Updated"})
                assert result is False

    def test_delete_nonexistent_message(self):
        """Test deleting a message that doesn't exist."""
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                with patch('app.storage.deleted_messages_cache', []):
                    # Should not raise exception
                    result = delete_message("nonexistent-id")
                    assert result is False

    def test_malformed_redis_data_fallback(self):
        """Test handling of malformed data in Redis."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = b'malformed json data'
        
        with patch('app.storage.redis_client', mock_redis):
            with patch('app.storage.messages_cache', []):
                # Should fall back to empty list
                messages = get_messages()
                assert isinstance(messages, list)
                assert len(messages) == 0


class TestStorageDataIntegrity:
    """Test data integrity and consistency in storage operations."""

    def test_message_id_uniqueness(self):
        """Test that message IDs are unique."""
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                add_message({"name": "User 1", "text": "Message 1"})
                add_message({"name": "User 2", "text": "Message 2"})
                
                messages = get_messages()
                ids = [msg["id"] for msg in messages]
                assert len(ids) == len(set(ids))  # All IDs should be unique

    def test_message_field_preservation(self):
        """Test that all message fields are preserved during operations."""
        complex_message = {
            "id": "complex-1",
            "name": "Test User",
            "text": "Complex message",
            "timestamp": "2025-01-01T12:00:00Z",
            "vehicle": "SAR-78",
            "eta": "15 minutes",
            "eta_timestamp": "2025-01-01T12:15:00Z",
            "eta_minutes": 15,
            "arrival_status": "Responding",
            "confidence": 0.95,
            "custom_field": "custom_value"
        }
        
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                add_message(complex_message)
                messages = get_messages()
                
                retrieved_message = messages[0]
                for key, value in complex_message.items():
                    assert key in retrieved_message
                    assert retrieved_message[key] == value

    def test_concurrent_operations_handling(self):
        """Test handling of potentially concurrent operations."""
        # This is a basic test - in a real scenario, you'd test with actual threading
        with patch('app.storage.redis_client', None):
            with patch('app.storage.messages_cache', []):
                # Add multiple messages "concurrently"
                for i in range(10):
                    add_message({"id": f"concurrent-{i}", "name": f"User {i}", "text": f"Message {i}"})
                
                messages = get_messages()
                assert len(messages) == 10
                
                # All messages should be retrievable
                for i in range(10):
                    found = any(msg["id"] == f"concurrent-{i}" for msg in messages)
                    assert found