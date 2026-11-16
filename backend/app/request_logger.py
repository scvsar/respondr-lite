"""HTTP Request logging to Azure Table Storage for debugging."""

import os
import time
import uuid
import logging
import asyncio
from typing import Optional
from datetime import datetime, timezone
from .config import is_testing

from azure.data.tables import TableServiceClient, TableEntity
from azure.core.exceptions import ResourceExistsError

logger = logging.getLogger(__name__)


class RequestLogger:
    """Log HTTP requests to Azure Table Storage for debugging."""
    
    def __init__(self):
        self.enabled = False
        self.table_client = None
        if is_testing or os.getenv('ENABLE_REQUEST_LOGGING', 'false').lower() != 'true':
            return
        
        # Only enable if connection string is available
        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if conn_str:
            try:
                table_name = os.getenv("REQUEST_LOG_TABLE", "RequestLogs")
                service_client = TableServiceClient.from_connection_string(conn_str, connection_timeout=5, read_timeout=15)
                
                # Create table if it doesn't exist
                try:
                    service_client.create_table(table_name)
                    logger.info(f"Created request log table: {table_name}")
                except ResourceExistsError:
                    pass
                
                self.table_client = service_client.get_table_client(table_name)
                self.enabled = True
                logger.info("Request logging to Azure Table Storage enabled")
            except Exception:
                logger.warning("Failed to initialize request logging")
    
    async def log_request(self, request, response=None, tag="HTTP_REQUEST"):
        """Log an HTTP request to Azure Table Storage."""
        if not self.enabled:
            return
        
        try:
            # Generate unique keys for Azure Table Storage
            current = datetime.now(timezone.utc)
            partition_key = current.strftime("%Y%m%d")
            row_key = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
            
            # Extract headers
            h = request.headers
            
            # Get client IP - try various sources
            client_ip = (
                h.get("cf-connecting-ip") or
                h.get("x-forwarded-for", "").split(",")[0].strip() or
                h.get("x-real-ip") or
                (request.client.host if request.client else "unknown")
            )
            
            # Build entity
            entity = {
                "PartitionKey": partition_key,
                "RowKey": row_key,
                "tag": tag,
                "timestamp": current.isoformat().replace('+00:00', 'Z'),
                "method": request.method,
                "path": str(request.url.path),
                "query": "",
                "client_ip": client_ip,
                "client_port": request.client.port if request.client else 0,
                "user_agent": h.get("user-agent", ""),
                "cf_ray": h.get("cf-ray", ""),
                "cf_connecting_ip": h.get("cf-connecting-ip", ""),
                "x_forwarded_for": h.get("x-forwarded-for", ""),
                "x_real_ip": h.get("x-real-ip", ""),
                "scheme": request.url.scheme,
                "host": h.get("host", ""),
                "full_url": str(request.url.replace(query="")),
                "status_code": response.status_code if response else 0,
                "x_ms_client_principal": h.get("x-ms-client-principal-name", ""),
                "x_auth_request_email": h.get("x-auth-request-email", ""),
                "referer": "",
                "origin": h.get("origin", ""),
            }
            
            # Add any Azure Container Apps specific headers
            if "x-ms-containerapp-name" in h:
                entity["containerapp_name"] = h.get("x-ms-containerapp-name", "")
            if "x-ms-containerapp-revision" in h:
                entity["containerapp_revision"] = h.get("x-ms-containerapp-revision", "")
            
            # Log to table (fire and forget)
            asyncio.create_task(self._insert_entity(entity))
            
        except Exception:
            # Don't let logging errors affect the application
            logger.error("Failed to log request")
    
    async def _insert_entity(self, entity):
        """Insert entity to Azure Table Storage."""
        try:
            await asyncio.to_thread(self.table_client.create_entity, entity)
        except Exception:
            logger.error("Failed to insert request log")


# Global instance
_request_logger = RequestLogger()


async def log_request(request, response=None, tag="HTTP_REQUEST"):
    """Log an HTTP request to Azure Table Storage."""
    await _request_logger.log_request(request, response, tag)
