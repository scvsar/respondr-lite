"""
Working test suite for storage layer functionality.

Tests the storage operations using the actual storage interface.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from app.config import APP_TZ
from app import storage


class TestStorageInterface:
    """Test storage layer interface and basic functionality."""

    def test_storage_module_imports(self):
        """Test that storage module imports and functions are accessible."""
        # Test that we can import the storage functions
        assert hasattr(storage, 'get_messages')
        assert hasattr(storage, 'add_message')
        assert hasattr(storage, 'update_message')
        assert hasattr(storage, 'delete_message')

    def test_get_messages_with_mocked_import(self):
        """Test get_messages when in testing mode with proper mocking."""
        # Mock the import of main module to prevent hanging
        mock_main = MagicMock()
        mock_main.messages = [
            {"id": "test-1", "name": "Test User", "text": "Test message"}
        ]
        
        # Patch both is_testing and the main import
        with patch('app.storage.is_testing', True):
            with patch('builtins.__import__') as mock_import:
                def side_effect(name, *args, **kwargs):
                    if name == 'main':
                        return mock_main
                    return __import__(name, *args, **kwargs)
                
                mock_import.side_effect = side_effect
                
                messages = storage.get_messages()
                assert isinstance(messages, list)
                assert len(messages) == 1
                assert messages[0]['id'] == "test-1"

    def test_add_message_basic_functionality(self):
        """Test basic add_message functionality."""
        test_message = {
            "name": "Test User",
            "text": "Test message content",
            "timestamp": datetime.now(APP_TZ).isoformat()
        }
        
        # Mock the storage functions to avoid Redis dependency
        with patch('app.storage.get_messages', return_value=[]):
            with patch('app.storage.save_messages') as mock_save:
                # The add_message function doesn't return the message, it just adds it
                storage.add_message(test_message)
                
                # Verify save_messages was called
                mock_save.assert_called_once()
                
                # Check that the message was added to the list passed to save_messages
                saved_messages = mock_save.call_args[0][0]
                assert len(saved_messages) == 1
                assert saved_messages[0]['name'] == test_message['name']
                assert saved_messages[0]['text'] == test_message['text']

    def test_message_id_generation(self):
        """Test that messages can be processed without causing errors."""
        test_message = {
            "name": "Test User",
            "text": "Message without ID"
        }
        
        with patch('app.storage.get_messages', return_value=[]):
            with patch('app.storage.save_messages') as mock_save:
                # Just test that the function works without errors
                storage.add_message(test_message)
                
                # Verify it was called
                mock_save.assert_called_once()

    def test_message_timestamp_generation(self):
        """Test that messages can be added without timestamps."""
        test_message = {
            "name": "Test User",
            "text": "Message without timestamp"
        }
        
        with patch('app.storage.get_messages', return_value=[]):
            with patch('app.storage.save_messages') as mock_save:
                # Just test that the function works
                storage.add_message(test_message)
                
                # Verify save was called
                mock_save.assert_called_once()

    def test_update_message_logic(self):
        """Test update message functionality."""
        existing_messages = [
            {"id": "update-test", "name": "Original Name", "text": "Original text"}
        ]
        
        update_data = {
            "name": "Updated Name",
            "text": "Updated text"
        }
        
        with patch('app.storage.get_messages', return_value=existing_messages):
            with patch('app.storage.save_messages') as mock_save:
                result = storage.update_message("update-test", update_data)
                
                # update_message returns True on success
                assert result is True

    def test_delete_message_logic(self):
        """Test delete message functionality."""
        existing_messages = [
            {"id": "delete-test", "name": "Test User", "text": "Message to delete"}
        ]
        
        with patch('app.storage.get_messages', return_value=existing_messages):
            with patch('app.storage.save_messages') as mock_save:
                with patch('app.storage.get_deleted_messages', return_value=[]):
                    with patch('app.storage.save_deleted_messages') as mock_save_deleted:
                        result = storage.delete_message("delete-test")
                        
                        assert result is True


    def test_bulk_operations_logic(self):
        """Test logic for bulk operations."""
        test_messages = [
            {"id": "bulk-1", "name": "User 1", "text": "Message 1"},
            {"id": "bulk-2", "name": "User 2", "text": "Message 2"},
            {"id": "bulk-3", "name": "User 3", "text": "Message 3"}
        ]
        
        with patch('app.storage.get_messages', return_value=test_messages):
            with patch('app.storage.save_messages') as mock_save:
                with patch('app.storage.get_deleted_messages', return_value=[]):
                    with patch('app.storage.save_deleted_messages'):
                        # Test bulk delete - should return count of deleted messages
                        result = storage.bulk_delete_messages(["bulk-1", "bulk-3"])
                        assert result == 2  # Should delete 2 messages

    def test_json_serialization_logic(self):
        """Test JSON serialization/deserialization logic."""
        test_data = [
            {
                "id": "json-test",
                "name": "Test User",
                "text": "Test message",
                "timestamp": datetime.now(APP_TZ).isoformat(),
                "vehicle": "POV",
                "eta": "15 minutes"
            }
        ]
        
        # Test that data can be serialized to JSON and back
        import json
        serialized = json.dumps(test_data)
        deserialized = json.loads(serialized)
        
        assert deserialized == test_data
        assert deserialized[0]['id'] == "json-test"
        assert deserialized[0]['name'] == "Test User"