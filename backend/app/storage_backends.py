"""
Storage backends for Respondr - pluggable storage implementations.
"""

import os, json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum


logger = logging.getLogger(__name__)


class StorageBackend(Enum):
    """Available storage backend types."""
    MEMORY = "memory"
    AZURE_TABLE = "azure_table"
    FILE = "file"


class BaseStorage(ABC):
    """Abstract base class for storage implementations."""
    
    @abstractmethod
    def get_messages(self) -> List[Dict[str, Any]]:
        """Get all active messages."""
        pass
    
    @abstractmethod
    def save_messages(self, messages: List[Dict[str, Any]]) -> bool:
        """Save all active messages. Returns True on success."""
        pass
    
    @abstractmethod
    def get_deleted_messages(self) -> List[Dict[str, Any]]:
        """Get all deleted messages."""
        pass
    
    @abstractmethod
    def save_deleted_messages(self, messages: List[Dict[str, Any]]) -> bool:
        """Save all deleted messages. Returns True on success."""
        pass
    
    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if storage backend is healthy and responsive."""
        pass
    
    @property
    @abstractmethod
    def backend_type(self) -> StorageBackend:
        """Return the storage backend type."""
        pass


class MemoryStorage(BaseStorage):
    """In-memory storage implementation."""
    
    def __init__(self):
        self._messages: List[Dict[str, Any]] = []
        self._deleted_messages: List[Dict[str, Any]] = []
        logger.info("Initialized in-memory storage")
    
    def get_messages(self) -> List[Dict[str, Any]]:
        return self._messages.copy()
    
    def save_messages(self, messages: List[Dict[str, Any]]) -> bool:
        self._messages = messages.copy()
        return True
    
    def get_deleted_messages(self) -> List[Dict[str, Any]]:
        return self._deleted_messages.copy()
    
    def save_deleted_messages(self, messages: List[Dict[str, Any]]) -> bool:
        self._deleted_messages = messages.copy()
        return True
    
    def is_healthy(self) -> bool:
        return True
    
    @property
    def backend_type(self) -> StorageBackend:
        return StorageBackend.MEMORY




class FileStorage(BaseStorage):
    """File-based storage implementation."""
    
    def __init__(self, messages_file: str = "messages.json", 
                 deleted_file: str = "deleted_messages.json"):
        self.messages_file = messages_file
        self.deleted_file = deleted_file
        logger.info(f"Initialized file storage: {messages_file}, {deleted_file}")
    
    def _read_json_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Read JSON data from file."""
        try:
            import os
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read {filepath}: {e}")
        return []
    
    def _write_json_file(self, filepath: str, data: List[Dict[str, Any]]) -> bool:
        """Write JSON data to file."""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to write {filepath}: {e}")
            return False
    
    def get_messages(self) -> List[Dict[str, Any]]:
        return self._read_json_file(self.messages_file)
    
    def save_messages(self, messages: List[Dict[str, Any]]) -> bool:
        return self._write_json_file(self.messages_file, messages)
    
    def get_deleted_messages(self) -> List[Dict[str, Any]]:
        return self._read_json_file(self.deleted_file)
    
    def save_deleted_messages(self, messages: List[Dict[str, Any]]) -> bool:
        return self._write_json_file(self.deleted_file, messages)
    
    def is_healthy(self) -> bool:
        # File storage is always "healthy" - worst case we create new files
        return True
    
    @property
    def backend_type(self) -> StorageBackend:
        return StorageBackend.FILE


class AzureTableStorage(BaseStorage):
    """Azure Table Storage implementation."""
    
    def __init__(self, connection_string: str, table_name: Optional[str] = None):
        # Prefer env var STORAGE_TABLE_NAME, then provided table_name, then default
        self.table_name = os.getenv("STORAGE_TABLE_NAME") or table_name or "responder-messages"
        self.connection_string = connection_string
        self._client = None
        self._last_health_check = 0
        self._is_healthy_cached = False
        
        # Try to initialize connection
        self._init_client()
    
    def _init_client(self):
        """Initialize Azure Table Storage client."""
        try:
            from azure.data.tables import TableServiceClient
            from azure.core.exceptions import ServiceRequestError
            
            if not self.connection_string:
                logger.warning("Azure Table Storage connection string is empty")
                self._client = None
                self._is_healthy_cached = False
                return
            
            self._client = TableServiceClient.from_connection_string(self.connection_string)
            
            # Create table if it doesn't exist
            try:
                self._client.create_table_if_not_exists(self.table_name)
                logger.info(f"Connected to Azure Table Storage: {self.table_name}")
                self._is_healthy_cached = True
            except Exception as e:
                logger.warning(f"Failed to create/verify table {self.table_name}: {e}")
                self._is_healthy_cached = False
                
        except ImportError:
            logger.error("Azure Table Storage client not available. Install with: pip install azure-data-tables")
            self._client = None
            self._is_healthy_cached = False
        except Exception as e:
            logger.warning(f"Azure Table Storage connection failed: {e}")
            self._client = None
            self._is_healthy_cached = False
    
    def is_healthy(self) -> bool:
        """Check Azure Table Storage health with basic caching."""
        current_time = datetime.now().timestamp()
        
        # Only check every 30 seconds
        if current_time - self._last_health_check < 30:
            return self._is_healthy_cached
        
        self._last_health_check = current_time
        
        if self._client is None:
            self._init_client()
        
        if self._client is not None:
            try:
                # Simple health check - try to get table properties
                table_client = self._client.get_table_client(self.table_name)
                table_client.get_table_access_policy()
                self._is_healthy_cached = True
                return True
            except Exception as e:
                logger.warning(f"Azure Table Storage health check failed: {e}")
                self._is_healthy_cached = False
                self._client = None
        
        return False
    
    def _message_to_entity(self, message: Dict[str, Any], partition_key: str = "messages") -> Dict[str, Any]:
        """Convert message dictionary to Azure Table entity."""
        entity = {
            "PartitionKey": partition_key,
            "RowKey": message.get("id", "unknown"),
        }
        
        # Flatten the message for table storage
        for key, value in message.items():
            if key == "id":
                continue  # Already in RowKey
            elif key == "parsed" and isinstance(value, dict):
                # Flatten parsed data with prefix
                for parsed_key, parsed_value in value.items():
                    entity[f"parsed_{parsed_key}"] = str(parsed_value) if parsed_value is not None else ""
            else:
                # Store as string to avoid type issues
                entity[key] = str(value) if value is not None else ""
        
        return entity
    
    def _entity_to_message(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Azure Table entity back to message dictionary."""
        message = {
            "id": entity["RowKey"]
        }
        
        parsed_data = {}
        
        for key, value in entity.items():
            if key in ["PartitionKey", "RowKey", "Timestamp", "etag"]:
                continue  # Skip Azure Table metadata
            elif key.startswith("parsed_"):
                # Reconstruct parsed data
                parsed_key = key[7:]  # Remove "parsed_" prefix
                parsed_data[parsed_key] = value
            else:
                message[key] = value
        
        if parsed_data:
            message["parsed"] = parsed_data
        
        return message
    
    def get_messages(self) -> List[Dict[str, Any]]:
        """Get all active messages from Azure Table Storage."""
        if not self.is_healthy() or self._client is None:
            raise Exception("Azure Table Storage not available")
        
        try:
            table_client = self._client.get_table_client(self.table_name)
            
            # Query for messages (not deleted)
            entities = table_client.query_entities(
                query_filter="PartitionKey eq 'messages'",
                select=None
            )
            
            messages = []
            for entity in entities:
                try:
                    message = self._entity_to_message(entity)
                    messages.append(message)
                except Exception as e:
                    logger.warning(f"Failed to convert entity to message: {e}")
            
            return messages
            
        except Exception as e:
            logger.error(f"Failed to get messages from Azure Table Storage: {e}")
            raise
    
    def save_messages(self, messages: List[Dict[str, Any]]) -> bool:
        """Save all active messages to Azure Table Storage."""
        if not self.is_healthy() or self._client is None:
            return False
        
        try:
            table_client = self._client.get_table_client(self.table_name)
            
            # First, delete all existing messages
            try:
                existing_entities = table_client.query_entities(
                    query_filter="PartitionKey eq 'messages'",
                    select=["PartitionKey", "RowKey"]
                )
                
                for entity in existing_entities:
                    try:
                        table_client.delete_entity(entity["PartitionKey"], entity["RowKey"])
                    except Exception as e:
                        logger.warning(f"Failed to delete existing entity {entity['RowKey']}: {e}")
            except Exception as e:
                logger.warning(f"Failed to clear existing messages: {e}")
            
            # Insert new messages
            for message in messages:
                try:
                    entity = self._message_to_entity(message, "messages")
                    table_client.upsert_entity(entity)
                except Exception as e:
                    logger.error(f"Failed to save message {message.get('id', 'unknown')}: {e}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to save messages to Azure Table Storage: {e}")
            return False
    
    def get_deleted_messages(self) -> List[Dict[str, Any]]:
        """Get all deleted messages from Azure Table Storage."""
        if not self.is_healthy() or self._client is None:
            raise Exception("Azure Table Storage not available")
        
        try:
            table_client = self._client.get_table_client(self.table_name)
            
            # Query for deleted messages
            entities = table_client.query_entities(
                query_filter="PartitionKey eq 'deleted'",
                select=None
            )
            
            messages = []
            for entity in entities:
                try:
                    message = self._entity_to_message(entity)
                    messages.append(message)
                except Exception as e:
                    logger.warning(f"Failed to convert deleted entity to message: {e}")
            
            return messages
            
        except Exception as e:
            logger.error(f"Failed to get deleted messages from Azure Table Storage: {e}")
            raise
    
    def save_deleted_messages(self, messages: List[Dict[str, Any]]) -> bool:
        """Save all deleted messages to Azure Table Storage."""
        if not self.is_healthy() or self._client is None:
            return False
        
        try:
            table_client = self._client.get_table_client(self.table_name)
            
            # First, delete all existing deleted messages
            try:
                existing_entities = table_client.query_entities(
                    query_filter="PartitionKey eq 'deleted'",
                    select=["PartitionKey", "RowKey"]
                )
                
                for entity in existing_entities:
                    try:
                        table_client.delete_entity(entity["PartitionKey"], entity["RowKey"])
                    except Exception as e:
                        logger.warning(f"Failed to delete existing deleted entity {entity['RowKey']}: {e}")
            except Exception as e:
                logger.warning(f"Failed to clear existing deleted messages: {e}")
            
            # Insert deleted messages
            for message in messages:
                try:
                    entity = self._message_to_entity(message, "deleted")
                    table_client.upsert_entity(entity)
                except Exception as e:
                    logger.error(f"Failed to save deleted message {message.get('id', 'unknown')}: {e}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to save deleted messages to Azure Table Storage: {e}")
            return False
    
    @property
    def backend_type(self) -> StorageBackend:
        return StorageBackend.AZURE_TABLE
