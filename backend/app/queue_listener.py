"""Background task to process messages from Azure Storage Queue."""

import asyncio
import json
import logging
import os

from azure.storage.queue import QueueClient

from .routers.webhook import WebhookMessage, webhook_handler

logger = logging.getLogger(__name__)


async def ensure_queue_exists(queue: QueueClient, queue_name: str) -> bool:
    """Ensure the queue exists, creating it if necessary. Returns True if queue is accessible."""
    try:
        # Try to create the queue
        await asyncio.to_thread(queue.create_queue)
        logger.info(f"Created queue '{queue_name}' successfully")
        return True
    except Exception as e:
        error_msg = str(e).lower()
        if "already exists" in error_msg or "conflict" in error_msg:
            logger.info(f"Queue '{queue_name}' already exists")
            return True
        elif "forbidden" in error_msg or "unauthorized" in error_msg:
            logger.warning(f"No permission to create queue '{queue_name}', checking if it exists...")
            # Try to access existing queue
            try:
                await asyncio.to_thread(queue.get_queue_properties)
                logger.info(f"Queue '{queue_name}' exists and is accessible")
                return True
            except Exception as access_err:
                logger.error(f"Cannot access queue '{queue_name}': {access_err}")
                return False
        else:
            logger.error(f"Failed to create queue '{queue_name}': {e}")
            # Still try to check if queue exists
            try:
                await asyncio.to_thread(queue.get_queue_properties)
                logger.info(f"Queue '{queue_name}' exists despite creation error")
                return True
            except Exception:
                logger.error(f"Queue '{queue_name}' is not accessible")
                return False


async def listen_to_queue() -> None:
    """Continuously poll Azure Storage Queue and process messages."""
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    queue_name = os.getenv("STORAGE_QUEUE_NAME")

    if not conn_str or not queue_name:
        logger.warning("Queue connection not configured; skipping listener")
        return

    queue = QueueClient.from_connection_string(conn_str, queue_name)

    # Ensure queue exists before starting listener
    queue_ready = await ensure_queue_exists(queue, queue_name)
    if queue_ready:
        logger.info(f"Queue listener started for '{queue_name}'")
    else:
        logger.warning("Queue is not accessible, will retry periodically...")

    while True:
        try:
            messages = await asyncio.to_thread(
                queue.receive_messages, messages_per_page=5, visibility_timeout=30
            )
            for msg in messages:
                processing_success = False
                try:
                    payload = json.loads(msg.content)
                    web_msg = WebhookMessage(**payload)
                    await webhook_handler(web_msg, request=None, debug=False)
                    processing_success = True
                except Exception:
                    logger.exception("Failed processing queue message")
                    # Don't delete failed messages - let them retry after visibility timeout
                finally:
                    if processing_success:
                        try:
                            await asyncio.to_thread(queue.delete_message, msg)
                        except Exception:
                            logger.exception("Failed to delete processed message")
        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg or "does not exist" in error_msg:
                logger.warning(f"Queue '{queue_name}' not found, attempting to recreate...")
                queue_ready = await ensure_queue_exists(queue, queue_name)
                if not queue_ready:
                    logger.error("Failed to recreate queue, will retry later")
                await asyncio.sleep(10)  # Longer wait after queue recreation
            elif "unauthorized" in error_msg or "forbidden" in error_msg:
                logger.error("Access denied to queue - check credentials and permissions")
                await asyncio.sleep(30)  # Longer wait for permission issues
            else:
                logger.exception("Queue polling failed")
                await asyncio.sleep(5)

        await asyncio.sleep(1)

