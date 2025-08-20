"""Storage layer for Respondr messages using Redis."""

import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import redis

from .config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_KEY, REDIS_DELETED_KEY, is_testing

logger = logging.getLogger(__name__)

# Global storage - Redis client or in-memory for tests
_redis_client = None
_test_messages: List[Dict[str, Any]] = []
_test_deleted_messages: List[Dict[str, Any]] = []


def get_redis_client():
    """Get Redis client, initializing if needed."""
    global _redis_client
    
    if is_testing:
        return None  # Use in-memory storage for tests
    
    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True
            )
            # Test connection
            _redis_client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            _redis_client = None
    
    return _redis_client


def get_messages() -> List[Dict[str, Any]]:
    """Get all active messages."""
    if is_testing:
        # Return the global test messages that can be patched
        import main
        return getattr(main, 'messages', _test_messages)
    
    redis_client = get_redis_client()
    if redis_client:
        try:
            data = redis_client.get(REDIS_KEY)
            if data and isinstance(data, str):
                return json.loads(data)
        except Exception as e:
            logger.error(f"Failed to get messages from Redis: {e}")
    
    return []


def save_messages(messages: List[Dict[str, Any]]):
    """Save all active messages."""
    if is_testing:
        # Update the global test messages
        import main
        if hasattr(main, 'messages'):
            main.messages[:] = messages
        else:
            _test_messages[:] = messages
        return
    
    redis_client = get_redis_client()
    if redis_client:
        try:
            redis_client.set(REDIS_KEY, json.dumps(messages))
        except Exception as e:
            logger.error(f"Failed to save messages to Redis: {e}")


def add_message(message: Dict[str, Any]):
    """Add a new message."""
    messages = get_messages()
    messages.append(message)
    save_messages(messages)


def get_deleted_messages() -> List[Dict[str, Any]]:
    """Get all deleted messages."""
    if is_testing:
        return _test_deleted_messages
    
    redis_client = get_redis_client()
    if redis_client:
        try:
            data = redis_client.get(REDIS_DELETED_KEY)
            if data and isinstance(data, str):
                return json.loads(data)
        except Exception as e:
            logger.error(f"Failed to get deleted messages from Redis: {e}")
    
    return []


def save_deleted_messages(messages: List[Dict[str, Any]]):
    """Save all deleted messages."""
    if is_testing:
        _test_deleted_messages[:] = messages
        return
    
    redis_client = get_redis_client()
    if redis_client:
        try:
            redis_client.set(REDIS_DELETED_KEY, json.dumps(messages))
        except Exception as e:
            logger.error(f"Failed to save deleted messages to Redis: {e}")


def delete_message(msg_id: str) -> bool:
    """Soft delete a message by moving it to deleted collection."""
    messages = get_messages()
    deleted_messages = get_deleted_messages()
    
    for i, msg in enumerate(messages):
        if msg.get("id") == msg_id:
            deleted_msg = messages.pop(i)
            deleted_msg["deleted_at"] = datetime.now().isoformat()
            deleted_messages.append(deleted_msg)
            
            save_messages(messages)
            save_deleted_messages(deleted_messages)
            return True
    
    return False


def update_message(msg_id: str, updates: Dict[str, Any]) -> bool:
    """Update a message."""
    messages = get_messages()
    
    for msg in messages:
        if msg.get("id") == msg_id:
            msg.update(updates)
            save_messages(messages)
            return True
    
    return False


def clear_all_messages():
    """Move all active messages to deleted."""
    messages = get_messages()
    deleted_messages = get_deleted_messages()
    
    timestamp = datetime.now().isoformat()
    for msg in messages:
        msg["deleted_at"] = timestamp
        deleted_messages.append(msg)
    
    save_messages([])
    save_deleted_messages(deleted_messages)
    
    return len(messages)


def undelete_message(msg_id: str) -> bool:
    """Restore a deleted message."""
    messages = get_messages()
    deleted_messages = get_deleted_messages()
    
    for i, msg in enumerate(deleted_messages):
        if msg.get("id") == msg_id:
            restored_msg = deleted_messages.pop(i)
            restored_msg.pop("deleted_at", None)
            messages.append(restored_msg)
            
            save_messages(messages)
            save_deleted_messages(deleted_messages)
            return True
    
    return False


def permanently_delete_message(msg_id: str) -> bool:
    """Permanently delete a message from deleted collection."""
    deleted_messages = get_deleted_messages()
    
    for i, msg in enumerate(deleted_messages):
        if msg.get("id") == msg_id:
            deleted_messages.pop(i)
            save_deleted_messages(deleted_messages)
            return True
    
    return False


def clear_all_deleted_messages():
    """Permanently delete all deleted messages."""
    deleted_messages = get_deleted_messages()
    count = len(deleted_messages)
    save_deleted_messages([])
    return count


def bulk_delete_messages(msg_ids: List[str]) -> int:
    """Bulk delete multiple messages."""
    messages = get_messages()
    deleted_messages = get_deleted_messages()
    
    deleted_count = 0
    timestamp = datetime.now().isoformat()
    
    # Process from end to beginning to avoid index shifting
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("id") in msg_ids:
            deleted_msg = messages.pop(i)
            deleted_msg["deleted_at"] = timestamp
            deleted_messages.append(deleted_msg)
            deleted_count += 1
    
    save_messages(messages)
    save_deleted_messages(deleted_messages)
    
    return deleted_count
