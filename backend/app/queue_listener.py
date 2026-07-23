"""Background task to process messages from Azure Storage Queue."""

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

from azure.storage.queue import QueueClient

from .routers.webhook import WebhookMessage, webhook_handler

logger = logging.getLogger(__name__)

DEFAULT_VISIBILITY_TIMEOUT_SECONDS = 300
DEFAULT_VISIBILITY_RENEWAL_SECONDS = 120


def _positive_int_setting(name: str, default: int) -> int:
    """Read a positive integer setting."""
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("Invalid %s setting; using %s", name, default)
        return default

    if value < 1:
        logger.warning("Invalid %s setting; using %s", name, default)
        return default

    return value


def _queue_timing_settings() -> tuple[int, int]:
    """Return the visibility timeout and renewal interval."""
    visibility_timeout = _positive_int_setting(
        "QUEUE_VISIBILITY_TIMEOUT_SECONDS",
        DEFAULT_VISIBILITY_TIMEOUT_SECONDS,
    )
    renewal_interval = _positive_int_setting(
        "QUEUE_VISIBILITY_RENEWAL_SECONDS",
        DEFAULT_VISIBILITY_RENEWAL_SECONDS,
    )
    if renewal_interval >= visibility_timeout:
        renewal_interval = max(1, visibility_timeout // 2)
        logger.warning(
            "Queue visibility renewal must be shorter than the timeout; using %s",
            renewal_interval,
        )

    return visibility_timeout, renewal_interval


def _get_queue_api_version(conn_str: str) -> Optional[str]:
    """Return an explicit queue API version when needed (primarily for Azurite)."""
    explicit_version = os.getenv("AZURE_STORAGE_QUEUE_API_VERSION", "").strip()
    if explicit_version:
        return explicit_version

    lowered = conn_str.lower()
    is_azurite = (
        "devstoreaccount1" in lowered
        or "127.0.0.1:10001" in lowered
        or "localhost:10001" in lowered
        or "azurite:10001" in lowered
    )
    if is_azurite:
        return "2021-12-02"

    return None


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


async def _renew_message_visibility(
    queue: QueueClient,
    message_state: Dict[str, Any],
    stop_event: asyncio.Event,
    visibility_timeout: int,
    renewal_interval: int,
) -> None:
    """Renew one message lease until processing stops."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=renewal_interval)
            return
        except asyncio.TimeoutError:
            updated_message = await asyncio.to_thread(
                queue.update_message,
                message_state["message"],
                visibility_timeout=visibility_timeout,
            )
            message_state["message"] = updated_message
            logger.debug("Renewed queue message visibility")


async def process_queue_message(
    queue: QueueClient,
    message: Any,
    visibility_timeout: int,
    renewal_interval: int,
) -> bool:
    """Process and delete one queue message."""
    message_state: Dict[str, Any] = {"message": message}
    stop_event = asyncio.Event()
    renewal_task = asyncio.create_task(
        _renew_message_visibility(
            queue,
            message_state,
            stop_event,
            visibility_timeout,
            renewal_interval,
        )
    )
    processing_success = False

    try:
        payload = json.loads(message.content)
        web_msg = WebhookMessage(**payload)
        await webhook_handler(web_msg, request=None, debug=False)
        processing_success = True
    except Exception:
        logger.exception("Failed processing queue message")
    finally:
        stop_event.set()
        try:
            await renewal_task
        except Exception:
            logger.exception("Failed to renew queue message visibility")

    if not processing_success:
        return False

    try:
        await asyncio.to_thread(
            queue.delete_message,
            message_state["message"],
        )
        return True
    except Exception:
        logger.exception("Failed to delete processed message")
        return False


async def listen_to_queue() -> None:
    """Continuously poll Azure Storage Queue and process messages."""
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    queue_name = os.getenv("STORAGE_QUEUE_NAME")

    if not conn_str or not queue_name:
        logger.warning("Queue connection not configured; skipping listener")
        return

    queue_api_version = _get_queue_api_version(conn_str)
    if queue_api_version:
        logger.info("Using queue API version %s", queue_api_version)
        queue = QueueClient.from_connection_string(
            conn_str,
            queue_name,
            api_version=queue_api_version,
        )
    else:
        queue = QueueClient.from_connection_string(conn_str, queue_name)

    # Ensure queue exists before starting listener
    queue_ready = await ensure_queue_exists(queue, queue_name)
    if queue_ready:
        logger.info(f"Queue listener started for '{queue_name}'")
    else:
        logger.warning("Queue is not accessible, will retry periodically...")

    visibility_timeout, renewal_interval = _queue_timing_settings()

    while True:
        try:
            messages = await asyncio.to_thread(
                queue.receive_messages,
                messages_per_page=1,
                max_messages=1,
                visibility_timeout=visibility_timeout,
            )
            for msg in messages:
                await process_queue_message(
                    queue,
                    msg,
                    visibility_timeout,
                    renewal_interval,
                )
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

