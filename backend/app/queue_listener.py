"""Background task to process messages from Azure Storage Queue."""

import asyncio
import json
import logging
import os

from azure.storage.queue import QueueClient

from .routers.webhook import WebhookMessage, webhook_handler

logger = logging.getLogger(__name__)


async def listen_to_queue() -> None:
    """Continuously poll Azure Storage Queue and process messages."""
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    queue_name = os.getenv("STORAGE_QUEUE_NAME")

    if not conn_str or not queue_name:
        logger.warning("Queue connection not configured; skipping listener")
        return

    queue = QueueClient.from_connection_string(conn_str, queue_name)

    while True:
        try:
            messages = await asyncio.to_thread(
                queue.receive_messages, messages_per_page=5, visibility_timeout=30
            )
            for msg in messages:
                try:
                    payload = json.loads(msg.content)
                    web_msg = WebhookMessage(**payload)
                    await webhook_handler(web_msg, request=None, debug=False)
                except Exception:
                    logger.exception("Failed processing queue message")
                finally:
                    await asyncio.to_thread(queue.delete_message, msg)
        except Exception:
            logger.exception("Queue polling failed")
            await asyncio.sleep(5)

        await asyncio.sleep(1)

