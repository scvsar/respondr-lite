"""Regression tests for duplicate GroupMe queue delivery."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.queue_listener import process_queue_message
from app.routers.webhook import (
    WebhookMessage,
    _build_storage_message_id,
    webhook_handler,
)
from app.storage_backends import AzureTableStorage, MemoryStorage


def _parsed_response():
    return {
        "vehicle": "POV",
        "eta": "15 minutes",
        "eta_timestamp": "2026-07-23 15:15:00",
        "eta_timestamp_utc": "2026-07-23T22:15:00+00:00",
        "minutes_until_arrival": 15,
        "arrival_status": "Responding",
        "raw_status": "Responding",
        "status_source": "LLM",
        "status_confidence": 0.99,
    }


def test_source_message_id_is_stable_and_scoped_to_group():
    first = _build_storage_message_id("group-1", "message-1")
    retry = _build_storage_message_id("group-1", "message-1")
    other_group = _build_storage_message_id("group-2", "message-1")

    assert first == retry
    assert first != other_group
    assert first.startswith("groupme-")


def test_memory_storage_upserts_one_message_without_removing_others():
    storage = MemoryStorage()
    storage.add_message({"id": "stable-1", "text": "first"})
    storage.add_message({"id": "stable-2", "text": "other"})
    storage.add_message({"id": "stable-1", "text": "retry"})

    messages = sorted(storage.get_messages(), key=lambda item: item["id"])

    assert messages == [
        {"id": "stable-1", "text": "retry"},
        {"id": "stable-2", "text": "other"},
    ]


def test_azure_storage_add_message_uses_one_atomic_upsert():
    table_client = MagicMock()
    service_client = MagicMock()
    service_client.get_table_client.return_value = table_client

    storage = AzureTableStorage.__new__(AzureTableStorage)
    storage.table_name = "ResponderMessages"
    storage._client = service_client
    storage._is_healthy_cached = True
    storage._last_health_check = 0

    with patch.object(storage, "is_healthy", return_value=True):
        result = storage.add_message(
            {
                "id": "stable-1",
                "groupme_id": "source-1",
                "text": "synthetic",
            }
        )

    assert result is True
    table_client.upsert_entity.assert_called_once()
    table_client.query_entities.assert_not_called()
    table_client.delete_entity.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_webhook_delivery_runs_extraction_once_and_stores_one_row():
    stored_messages = []

    def add_or_replace(message):
        stored_messages[:] = [
            item for item in stored_messages if item["id"] != message["id"]
        ]
        stored_messages.append(message)
        return True

    message = WebhookMessage(
        id="source-message-1",
        group_id="synthetic-group",
        name="Synthetic Responder",
        text="Responding in POV with ETA 15 minutes.",
        created_at=1784844000,
    )

    with (
        patch(
            "app.routers.webhook.get_messages",
            side_effect=lambda: list(stored_messages),
        ),
        patch(
            "app.routers.webhook.add_message",
            side_effect=add_or_replace,
        ),
        patch(
            "app.routers.webhook.extract_details_from_text",
            return_value=_parsed_response(),
        ) as extract,
    ):
        first = await webhook_handler(message, request=None, debug=False)
        retry = await webhook_handler(message, request=None, debug=False)

    assert first == {"status": "ok"}
    assert retry == {"status": "duplicate"}
    assert len(stored_messages) == 1
    assert stored_messages[0]["groupme_id"] == "source-message-1"
    assert extract.call_count == 1


@pytest.mark.asyncio
async def test_slow_queue_processing_renews_visibility_and_deletes_latest_receipt():
    payload = {
        "id": "source-message-1",
        "group_id": "synthetic-group",
        "name": "Synthetic Responder",
        "text": "Responding in POV with ETA 15 minutes.",
        "created_at": 1784844000,
    }
    original = SimpleNamespace(
        content=json.dumps(payload),
        id="queue-message-1",
        pop_receipt="receipt-0",
    )
    queue = MagicMock()
    receipt_number = 0

    def update_message(message, visibility_timeout):
        nonlocal receipt_number
        receipt_number += 1
        return SimpleNamespace(
            content=message.content,
            id=message.id,
            pop_receipt=f"receipt-{receipt_number}",
        )

    queue.update_message.side_effect = update_message

    async def slow_handler(*args, **kwargs):
        await asyncio.sleep(0.04)
        return {"status": "ok"}

    with patch(
        "app.queue_listener.webhook_handler",
        side_effect=slow_handler,
    ):
        result = await process_queue_message(
            queue,
            original,
            visibility_timeout=2,
            renewal_interval=0.01,
        )

    assert result is True
    assert queue.update_message.call_count >= 1
    deleted_message = queue.delete_message.call_args.args[0]
    assert deleted_message.pop_receipt == f"receipt-{receipt_number}"


@pytest.mark.asyncio
async def test_failed_queue_processing_does_not_delete_message():
    message = SimpleNamespace(
        content="{invalid-json",
        id="queue-message-1",
        pop_receipt="receipt-0",
    )
    queue = MagicMock()

    result = await process_queue_message(
        queue,
        message,
        visibility_timeout=2,
        renewal_interval=1,
    )

    assert result is False
    queue.delete_message.assert_not_called()
