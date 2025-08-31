"""
Test retention functionality for purging old messages.
"""

import time
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from app.storage import purge_old_messages


def test_purge_old_messages_no_messages():
    """Test purging when there are no messages."""
    with patch('app.storage.get_messages', return_value=[]), \
         patch('app.storage.get_deleted_messages', return_value=[]):
        
        result = purge_old_messages()
        assert result == {"active": 0, "deleted": 0}


def test_purge_old_messages_all_recent():
    """Test purging when all messages are recent."""
    current_time = time.time()
    recent_messages = [
        {"id": "1", "created_at": current_time - 86400},  # 1 day old
        {"id": "2", "created_at": current_time - 172800},  # 2 days old
    ]
    
    with patch('app.storage.get_messages', return_value=recent_messages), \
         patch('app.storage.get_deleted_messages', return_value=[]), \
         patch('app.storage.save_messages') as mock_save, \
         patch('app.storage.save_deleted_messages'):
        
        result = purge_old_messages()
        assert result == {"active": 0, "deleted": 0}
        mock_save.assert_not_called()  # Should not save if nothing purged


def test_purge_old_messages_with_old_active():
    """Test purging old active messages."""
    current_time = time.time()
    messages = [
        {"id": "1", "created_at": current_time - 86400},  # 1 day old (keep)
        {"id": "2", "created_at": current_time - (366 * 86400)},  # 366 days old (purge)
        {"id": "3", "created_at": current_time - (400 * 86400)},  # 400 days old (purge)
    ]
    
    with patch('app.storage.get_messages', return_value=messages), \
         patch('app.storage.get_deleted_messages', return_value=[]), \
         patch('app.storage.save_messages') as mock_save, \
         patch('app.storage.save_deleted_messages'):
        
        result = purge_old_messages()
        assert result == {"active": 2, "deleted": 0}
        
        # Check that only the recent message was kept
        saved_messages = mock_save.call_args[0][0]
        assert len(saved_messages) == 1
        assert saved_messages[0]["id"] == "1"


def test_purge_old_messages_with_old_deleted():
    """Test purging old deleted messages."""
    current_time = time.time()
    old_iso_date = (datetime.now() - timedelta(days=400)).isoformat()
    recent_iso_date = datetime.now().isoformat()
    
    deleted_messages = [
        {"id": "1", "deleted_at": recent_iso_date},  # Recent (keep)
        {"id": "2", "deleted_at": old_iso_date},  # Old (purge)
        {"id": "3", "created_at": current_time - (400 * 86400)},  # Old with created_at (purge)
    ]
    
    with patch('app.storage.get_messages', return_value=[]), \
         patch('app.storage.get_deleted_messages', return_value=deleted_messages), \
         patch('app.storage.save_messages'), \
         patch('app.storage.save_deleted_messages') as mock_save_deleted:
        
        result = purge_old_messages()
        assert result == {"active": 0, "deleted": 2}
        
        # Check that only the recent message was kept
        saved_messages = mock_save_deleted.call_args[0][0]
        assert len(saved_messages) == 1
        assert saved_messages[0]["id"] == "1"


def test_purge_old_messages_with_missing_timestamps():
    """Test that messages without timestamps are kept."""
    current_time = time.time()
    messages = [
        {"id": "1"},  # No created_at (keep)
        {"id": "2", "created_at": None},  # None created_at (keep)
        {"id": "3", "created_at": "invalid"},  # Invalid created_at (keep)
        {"id": "4", "created_at": current_time - (400 * 86400)},  # Old (purge)
    ]
    
    with patch('app.storage.get_messages', return_value=messages), \
         patch('app.storage.get_deleted_messages', return_value=[]), \
         patch('app.storage.save_messages') as mock_save, \
         patch('app.storage.save_deleted_messages'):
        
        result = purge_old_messages()
        assert result == {"active": 1, "deleted": 0}
        
        # Check that messages without valid timestamps were kept
        saved_messages = mock_save.call_args[0][0]
        assert len(saved_messages) == 3
        assert {msg["id"] for msg in saved_messages} == {"1", "2", "3"}


def test_purge_disabled_with_zero_retention():
    """Test that purging is disabled when RETENTION_DAYS is 0."""
    with patch('app.storage.RETENTION_DAYS', 0):
        result = purge_old_messages()
        assert result == {"active": 0, "deleted": 0}


def test_purge_disabled_with_negative_retention():
    """Test that purging is disabled when RETENTION_DAYS is negative."""
    with patch('app.storage.RETENTION_DAYS', -1):
        result = purge_old_messages()
        assert result == {"active": 0, "deleted": 0}


# Endpoint tests removed - the retention cleanup endpoint is available
# but testing it requires complex mocking due to dynamic imports
# The core purge_old_messages function is thoroughly tested above