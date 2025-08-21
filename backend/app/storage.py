"""
Unified storage manager for Respondr with pluggable backends and automatic fallback.

This module provides a seamless storage abstraction that can work with Redis,
Azure Table Storage, file-based storage, or in-memory storage with automatic
fallback when primary storage is unavailable.
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from .storage_backends import (
    BaseStorage, StorageBackend, MemoryStorage, RedisStorage, 
    FileStorage, AzureTableStorage
)
from .config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_KEY, REDIS_DELETED_KEY, is_testing

logger = logging.getLogger(__name__)

# Legacy test storage for backwards compatibility
_test_messages: List[Dict[str, Any]] = []
_test_deleted_messages: List[Dict[str, Any]] = []


class StorageManager:
    """
    Unified storage manager with automatic fallback capabilities.
    
    Features:
    - Configurable primary and fallback storage backends
    - Automatic failover when primary storage is unavailable
    - Seamless API that abstracts storage implementation details
    - Support for Redis, Azure Table Storage, file, and in-memory storage
    """
    
    def __init__(self):
        self.primary_backend: Optional[BaseStorage] = None
        self.fallback_backend: Optional[BaseStorage] = None
        self.current_backend: Optional[BaseStorage] = None
        
        # Initialize based on configuration
        self._configure_backends()
    
    def _configure_backends(self):
        """Configure storage backends based on environment and availability."""
        
        # Handle testing mode
        if is_testing:
            self.primary_backend = MemoryStorage()
            self.fallback_backend = MemoryStorage()
            self.current_backend = self.primary_backend
            return
        
        # Determine primary backend from config
        primary_type = os.getenv("STORAGE_BACKEND", "redis").lower()
        fallback_type = os.getenv("STORAGE_FALLBACK", "memory").lower()
        
        logger.info(f"Configuring storage: primary={primary_type}, fallback={fallback_type}")
        
        # Create primary backend
        self.primary_backend = self._create_backend(primary_type)
        
        # Create fallback backend (different from primary)
        if fallback_type != primary_type:
            self.fallback_backend = self._create_backend(fallback_type)
        else:
            # If fallback is same as primary, use memory as ultimate fallback
            self.fallback_backend = MemoryStorage()
        
        # Set current backend
        self._select_active_backend()
    
    def _create_backend(self, backend_type: str) -> BaseStorage:
        """Create a storage backend instance."""
        
        if backend_type == "redis":
            return RedisStorage(
                host=REDIS_HOST, 
                port=REDIS_PORT, 
                db=REDIS_DB,
                messages_key=REDIS_KEY,
                deleted_key=REDIS_DELETED_KEY
            )
        
        elif backend_type == "azure_table":
            connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
            table_name = os.getenv("AZURE_TABLE_NAME", "responderMessages")
            return AzureTableStorage(connection_string, table_name)
        
        elif backend_type == "file":
            messages_file = os.getenv("STORAGE_MESSAGES_FILE", "messages.json")
            deleted_file = os.getenv("STORAGE_DELETED_FILE", "deleted_messages.json")
            return FileStorage(messages_file, deleted_file)
        
        elif backend_type == "memory":
            return MemoryStorage()
        
        else:
            logger.warning(f"Unknown storage backend '{backend_type}', falling back to memory")
            return MemoryStorage()
    
    def _select_active_backend(self):
        """Select the active backend based on health checks."""
        
        # Try primary backend first
        if self.primary_backend and self.primary_backend.is_healthy():
            if self.current_backend != self.primary_backend:
                logger.info(f"Using primary storage: {self.primary_backend.backend_type.value}")
                self.current_backend = self.primary_backend
            return
        
        # Fallback to secondary backend
        if self.fallback_backend and self.fallback_backend.is_healthy():
            if self.current_backend != self.fallback_backend:
                logger.warning(f"Primary storage unavailable, using fallback: {self.fallback_backend.backend_type.value}")
                self.current_backend = self.fallback_backend
            return
        
        # Ultimate fallback - create in-memory storage
        if not self.current_backend or not self.current_backend.is_healthy():
            logger.error("All configured storage backends failed, using emergency in-memory storage")
            self.current_backend = MemoryStorage()
    
    def _ensure_backend(self):
        """Ensure we have a working backend, checking health periodically."""
        
        # If current backend is unhealthy, try to switch
        if not self.current_backend or not self.current_backend.is_healthy():
            self._select_active_backend()
        
        # If we still don't have a backend, create emergency memory storage
        if not self.current_backend:
            logger.critical("No storage backend available, creating emergency memory storage")
            self.current_backend = MemoryStorage()
        
        # Ensure we definitely have a backend
        assert self.current_backend is not None, "Backend must be available after _ensure_backend"
    
    def get_messages(self) -> List[Dict[str, Any]]:
        """Get all active messages from storage."""
        
        # Handle legacy test mode
        if is_testing:
            import main
            return getattr(main, 'messages', _test_messages)
        
        self._ensure_backend()
        
        try:
            # Type checker workaround - we ensure backend is not None above
            backend = self.current_backend
            assert backend is not None
            
            messages = backend.get_messages()
            logger.debug(f"Retrieved {len(messages)} messages from {backend.backend_type.value}")
            return messages
        except Exception as e:
            backend = self.current_backend
            backend_name = backend.backend_type.value if backend else "unknown"
            logger.error(f"Failed to get messages from {backend_name}: {e}")
            
            # Try to switch to fallback
            if self.current_backend == self.primary_backend and self.fallback_backend:
                logger.warning("Switching to fallback storage due to error")
                self.current_backend = self.fallback_backend
                return self.get_messages()  # Recursive retry with fallback
            
            # Return empty list if all else fails
            return []
    
    def save_messages(self, messages: List[Dict[str, Any]]) -> bool:
        """Save all active messages to storage."""
        
        # Handle legacy test mode
        if is_testing:
            import main
            if hasattr(main, 'messages'):
                main.messages[:] = messages
            else:
                _test_messages[:] = messages
            return True
        
        self._ensure_backend()
        
        try:
            # Type checker workaround - we ensure backend is not None above
            backend = self.current_backend
            assert backend is not None
            
            success = backend.save_messages(messages)
            if success:
                logger.debug(f"Saved {len(messages)} messages to {backend.backend_type.value}")
            else:
                logger.warning(f"Failed to save messages to {backend.backend_type.value}")
            return success
        except Exception as e:
            backend = self.current_backend
            backend_name = backend.backend_type.value if backend else "unknown"
            logger.error(f"Failed to save messages to {backend_name}: {e}")
            
            # Try to switch to fallback
            if self.current_backend == self.primary_backend and self.fallback_backend:
                logger.warning("Switching to fallback storage for save operation")
                self.current_backend = self.fallback_backend
                return self.save_messages(messages)  # Recursive retry with fallback
            
            return False
    
    def get_deleted_messages(self) -> List[Dict[str, Any]]:
        """Get all deleted messages from storage."""
        
        # Handle legacy test mode
        if is_testing:
            return _test_deleted_messages
        
        self._ensure_backend()
        
        try:
            # Type checker workaround - we ensure backend is not None above
            backend = self.current_backend
            assert backend is not None
            
            messages = backend.get_deleted_messages()
            logger.debug(f"Retrieved {len(messages)} deleted messages from {backend.backend_type.value}")
            return messages
        except Exception as e:
            backend = self.current_backend
            backend_name = backend.backend_type.value if backend else "unknown"
            logger.error(f"Failed to get deleted messages from {backend_name}: {e}")
            
            # Try to switch to fallback
            if self.current_backend == self.primary_backend and self.fallback_backend:
                logger.warning("Switching to fallback storage due to error")
                self.current_backend = self.fallback_backend
                return self.get_deleted_messages()  # Recursive retry with fallback
            
            return []
    
    def save_deleted_messages(self, deleted_messages: List[Dict[str, Any]]) -> bool:
        """Save all deleted messages to storage."""
        
        # Handle legacy test mode
        if is_testing:
            _test_deleted_messages[:] = deleted_messages
            return True
        
        self._ensure_backend()
        
        try:
            # Type checker workaround - we ensure backend is not None above
            backend = self.current_backend
            assert backend is not None
            
            success = backend.save_deleted_messages(deleted_messages)
            if success:
                logger.debug(f"Saved {len(deleted_messages)} deleted messages to {backend.backend_type.value}")
            else:
                logger.warning(f"Failed to save deleted messages to {backend.backend_type.value}")
            return success
        except Exception as e:
            backend = self.current_backend
            backend_name = backend.backend_type.value if backend else "unknown"
            logger.error(f"Failed to save deleted messages to {backend_name}: {e}")
            
            # Try to switch to fallback
            if self.current_backend == self.primary_backend and self.fallback_backend:
                logger.warning("Switching to fallback storage for save operation")
                self.current_backend = self.fallback_backend
                return self.save_deleted_messages(deleted_messages)  # Recursive retry with fallback
            
            return False
    
    def get_storage_info(self) -> Dict[str, Any]:
        """Get information about current storage configuration."""
        return {
            "current_backend": self.current_backend.backend_type.value if self.current_backend else None,
            "primary_backend": self.primary_backend.backend_type.value if self.primary_backend else None,
            "fallback_backend": self.fallback_backend.backend_type.value if self.fallback_backend else None,
            "primary_healthy": self.primary_backend.is_healthy() if self.primary_backend else False,
            "fallback_healthy": self.fallback_backend.is_healthy() if self.fallback_backend else False,
            "current_healthy": self.current_backend.is_healthy() if self.current_backend else False,
        }


# Global storage manager instance
_storage_manager = StorageManager()


# Backwards-compatible API functions
def get_messages() -> List[Dict[str, Any]]:
    """Get all active messages from storage."""
    return _storage_manager.get_messages()


def save_messages(messages: List[Dict[str, Any]]):
    """Save all active messages to storage."""
    return _storage_manager.save_messages(messages)


def get_deleted_messages() -> List[Dict[str, Any]]:
    """Get all deleted messages from storage."""
    return _storage_manager.get_deleted_messages()


def save_deleted_messages(deleted_messages: List[Dict[str, Any]]):
    """Save all deleted messages to storage."""
    return _storage_manager.save_deleted_messages(deleted_messages)


def get_storage_info() -> Dict[str, Any]:
    """Get information about current storage configuration."""
    return _storage_manager.get_storage_info()


# Legacy Redis client function for backwards compatibility
def get_redis_client():
    """Get Redis client or None if not available."""
    if is_testing:
        return None
    
    current_backend = _storage_manager.current_backend
    if (current_backend and 
        current_backend.backend_type == StorageBackend.REDIS and
        hasattr(current_backend, '_client')):
        # Type check: we know this is RedisStorage, so _client exists
        redis_backend = current_backend  # type: ignore
        return redis_backend._client  # type: ignore
    return None


# Legacy functions that might be used by other parts of the codebase
def add_message(message: Dict[str, Any]):
    """Add a new message."""
    messages = get_messages()
    messages.append(message)
    save_messages(messages)


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
