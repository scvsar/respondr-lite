"""Tests for the recoverable duplicate cleanup plan."""

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "cleanup_duplicate_responders.py"
)
SPEC = importlib.util.spec_from_file_location(
    "cleanup_duplicate_responders",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)


def test_cleanup_plan_keeps_one_entity_per_groupme_id():
    entities = [
        {
            "PartitionKey": "messages",
            "RowKey": "old-b",
            "groupme_id": "source-1",
        },
        {
            "PartitionKey": "messages",
            "RowKey": "old-a",
            "groupme_id": "source-1",
        },
        {
            "PartitionKey": "messages",
            "RowKey": "only",
            "groupme_id": "source-2",
        },
    ]

    plan = cleanup.build_cleanup_plan(entities)

    assert len(plan) == 1
    groupme_id, keeper, removals = plan[0]
    assert groupme_id == "source-1"
    assert keeper["RowKey"] == "old-a"
    assert [entity["RowKey"] for entity in removals] == ["old-b"]


def test_cleanup_plan_prefers_stable_groupme_row_key():
    entities = [
        {
            "PartitionKey": "messages",
            "RowKey": "000-old",
            "groupme_id": "source-1",
        },
        {
            "PartitionKey": "messages",
            "RowKey": "groupme-stable",
            "groupme_id": "source-1",
        },
    ]

    plan = cleanup.build_cleanup_plan(entities)

    assert plan[0][1]["RowKey"] == "groupme-stable"
    assert plan[0][2][0]["RowKey"] == "000-old"


def test_cleanup_plan_prefers_confident_complete_legacy_row():
    entities = [
        {
            "PartitionKey": "messages",
            "RowKey": "old-a",
            "groupme_id": "source-1",
            "status_confidence": 0.60,
            "arrival_status": "Unknown",
            "vehicle": "Unknown",
            "eta": "Unknown",
            "eta_timestamp": "Unknown",
        },
        {
            "PartitionKey": "messages",
            "RowKey": "old-b",
            "groupme_id": "source-1",
            "status_confidence": 0.95,
            "arrival_status": "Responding",
            "vehicle": "POV",
            "eta": "20:15",
            "eta_timestamp": "2026-07-23T20:15:00-07:00",
        },
    ]

    plan = cleanup.build_cleanup_plan(entities)

    assert plan[0][1]["RowKey"] == "old-b"
    assert plan[0][2][0]["RowKey"] == "old-a"


def test_copy_to_backup_preserves_data_and_records_origin():
    table_client = type(
        "TableClientStub",
        (),
        {"upsert_entity": lambda self, entity: setattr(self, "entity", entity)},
    )()
    entity = {
        "PartitionKey": "messages",
        "RowKey": "old-a",
        "groupme_id": "source-1",
        "text": "Responding",
        "Timestamp": "service-managed",
        "etag": "service-managed",
    }

    cleanup.copy_to_backup(
        table_client,
        entity,
        "duplicate-cleanup-20260723",
        "2026-07-23T20:00:00+00:00",
    )

    assert table_client.entity == {
        "PartitionKey": "duplicate-cleanup-20260723",
        "RowKey": "old-a",
        "groupme_id": "source-1",
        "text": "Responding",
        "cleanup_original_partition": "messages",
        "cleanup_time_utc": "2026-07-23T20:00:00+00:00",
    }
