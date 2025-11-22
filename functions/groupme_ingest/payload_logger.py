"""Log incoming function payloads to Azure Table Storage for debugging."""

import os
import time
import uuid
import logging
import json
from typing import Any, Dict
from datetime import datetime

from azure.data.tables import TableServiceClient, TableEntity
from azure.core.exceptions import ResourceExistsError

logger = logging.getLogger(__name__)


class PayloadLogger:
    """Log incoming payloads to Azure Table Storage for debugging."""
    
    def __init__(self):
        self.enabled = False
        self.table_client = None
        
        # Check if payload logging is enabled via environment variable
        enable_logging = os.getenv("ENABLE_FUNCTION_PAYLOAD_LOGGING", "false").lower() == "true"
        if not enable_logging:
            logger.info("Function payload logging is disabled (set ENABLE_FUNCTION_PAYLOAD_LOGGING=true to enable)")
            return
        
        # Only enable if connection string is available
        conn_str = os.getenv("AzureWebJobsStorage")
        if conn_str:
            try:
                table_name = os.getenv("FUNCTION_PAYLOAD_TABLE", "FunctionIncoming")
                service_client = TableServiceClient.from_connection_string(conn_str)
                
                # Create table if it doesn't exist
                try:
                    service_client.create_table(table_name)
                    logger.info(f"Created payload log table: {table_name}")
                except ResourceExistsError:
                    pass
                
                self.table_client = service_client.get_table_client(table_name)
                self.enabled = True
                logger.info("Payload logging to Azure Table Storage enabled")
            except Exception as e:
                logger.warning(f"Failed to initialize payload logging: {e}")
    
    def log_payload(self, payload: Dict[str, Any], headers: Dict[str, str] = None, method: str = "POST"):
        """Log an incoming payload to Azure Table Storage."""
        if not self.enabled:
            return
        
        try:
            # Generate unique keys for Azure Table Storage
            partition_key = datetime.utcnow().strftime("%Y%m%d")  # Daily partitions
            row_key = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
            
            # Build entity
            entity = {
                "PartitionKey": partition_key,
                "RowKey": row_key,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "method": method,
                "payload": json.dumps(payload) if payload else "",
                "headers": json.dumps(headers) if headers else "",
                "group_id": payload.get("group_id", "") if payload else "",
                "message_id": payload.get("id", "") if payload else "",
                "sender_name": payload.get("name", "") if payload else "",
                "message_text": payload.get("text", "") if payload else "",
            }
            
            # Insert to table (synchronous for function context)
            self.table_client.create_entity(entity)
            logger.info("Logged incoming payload to storage table")
            
        except Exception as e:
            # Check for TableNotFound and try to recreate (self-healing)
            error_msg = str(e)
            if "TableNotFound" in error_msg or "ResourceNotFound" in error_msg or "404" in error_msg:
                try:
                    logger.info("Payload table not found, attempting to recreate...")
                    self.table_client.create_table()
                    
                    # Retry insert
                    self.table_client.create_entity(entity)
                    logger.info("Logged incoming payload to storage table (after recreation)")
                    return
                except Exception as recreate_e:
                    logger.error(f"Failed to recreate payload table: {recreate_e}")

            # Don't let logging errors affect the application
            logger.error(f"Failed to log payload: {e}")


# Global instance
_payload_logger = PayloadLogger()


def log_payload(payload: Dict[str, Any], headers: Dict[str, str] = None, method: str = "POST"):
    """Log an incoming payload to Azure Table Storage."""
    _payload_logger.log_payload(payload, headers, method)