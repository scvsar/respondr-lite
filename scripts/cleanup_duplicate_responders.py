#!/usr/bin/env python3
"""Move duplicate responder entities to a recovery partition."""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

from azure.core.credentials import AzureNamedKeyCredential
from azure.data.tables import TableClient


ACTIVE_PARTITION = "messages"
SYSTEM_FIELDS = {"PartitionKey", "RowKey", "Timestamp", "etag"}
UNKNOWN_VALUES = {"", "none", "not specified", "unknown"}


def _confidence(entity: Dict[str, Any]) -> float:
    """Return a sortable confidence value."""
    try:
        return float(entity.get("status_confidence", 0))
    except (TypeError, ValueError):
        return 0


def _completeness(entity: Dict[str, Any]) -> int:
    """Count useful extracted responder fields."""
    fields = ("arrival_status", "vehicle", "eta", "eta_timestamp")
    return sum(
        str(entity.get(field, "")).strip().lower() not in UNKNOWN_VALUES
        for field in fields
    )


def _timestamp(entity: Dict[str, Any]) -> float:
    """Return the Azure entity update time as a sortable value."""
    value = entity.get("Timestamp")
    if isinstance(value, datetime):
        return value.timestamp()
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0


def select_keeper(entities: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Select the best deterministic entity to keep active."""
    ordered = sorted(
        entities,
        key=lambda entity: (
            not str(entity["RowKey"]).startswith("groupme-"),
            -_confidence(entity),
            -_completeness(entity),
            -_timestamp(entity),
            str(entity["RowKey"]),
        ),
    )
    return ordered[0]


def build_cleanup_plan(
    entities: Iterable[Dict[str, Any]],
) -> List[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]]:
    """Return duplicate groups with one keeper and one removal list."""
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        groupme_id = str(entity.get("groupme_id", "")).strip()
        if groupme_id:
            groups[groupme_id].append(entity)

    plan = []
    for groupme_id, group in groups.items():
        if len(group) < 2:
            continue
        keeper = select_keeper(group)
        removals = [
            entity for entity in group if entity["RowKey"] != keeper["RowKey"]
        ]
        plan.append((groupme_id, keeper, removals))

    return sorted(plan, key=lambda item: item[0])


def copy_to_backup(
    table_client: TableClient,
    entity: Dict[str, Any],
    backup_partition: str,
    cleanup_time: str,
) -> None:
    """Copy one active entity to the recovery partition."""
    backup = {
        key: value
        for key, value in entity.items()
        if key not in SYSTEM_FIELDS
    }
    backup.update(
        {
            "PartitionKey": backup_partition,
            "RowKey": entity["RowKey"],
            "cleanup_original_partition": ACTIVE_PARTITION,
            "cleanup_time_utc": cleanup_time,
        }
    )
    table_client.upsert_entity(backup)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find duplicate active responder entities by GroupMe message ID. "
            "The default mode does not change data."
        )
    )
    parser.add_argument("--account-name", required=True)
    parser.add_argument("--table-name", default="ResponderMessages")
    parser.add_argument(
        "--account-key-env",
        default="AZURE_STORAGE_KEY",
        help="Environment variable that contains the storage account key.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Move excess entities to a recovery partition.",
    )
    parser.add_argument(
        "--backup-partition",
        help="Recovery partition name. This value is required with --apply.",
    )
    parser.add_argument(
        "--expected-removals",
        type=int,
        help=(
            "Expected excess entity count. This value is required with --apply "
            "and stops cleanup if the live count changed."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    account_key = os.getenv(args.account_key_env, "")
    if not account_key:
        print(
            f"Set {args.account_key_env} before you run this command.",
            file=sys.stderr,
        )
        return 2

    if args.apply and not args.backup_partition:
        print("--backup-partition is required with --apply.", file=sys.stderr)
        return 2
    if args.apply and args.backup_partition == ACTIVE_PARTITION:
        print(
            f"--backup-partition cannot be {ACTIVE_PARTITION}.",
            file=sys.stderr,
        )
        return 2
    if args.apply and args.expected_removals is None:
        print("--expected-removals is required with --apply.", file=sys.stderr)
        return 2

    credential = AzureNamedKeyCredential(args.account_name, account_key)
    table_client = TableClient(
        endpoint=f"https://{args.account_name}.table.core.windows.net",
        table_name=args.table_name,
        credential=credential,
    )
    entities = list(
        table_client.query_entities(
            f"PartitionKey eq '{ACTIVE_PARTITION}'"
        )
    )
    plan = build_cleanup_plan(entities)
    removal_count = sum(len(removals) for _, _, removals in plan)

    print(f"Active entities: {len(entities)}")
    print(f"Duplicate GroupMe IDs: {len(plan)}")
    print(f"Excess entities: {removal_count}")

    if not args.apply:
        print("Dry run complete. No data changed.")
        return 0
    if removal_count != args.expected_removals:
        print(
            "Cleanup stopped because the excess entity count changed. "
            f"Expected {args.expected_removals}, found {removal_count}.",
            file=sys.stderr,
        )
        return 1

    cleanup_time = datetime.now(timezone.utc).isoformat()
    moved = 0
    for _, _, removals in plan:
        for entity in removals:
            copy_to_backup(
                table_client,
                entity,
                args.backup_partition,
                cleanup_time,
            )
            table_client.delete_entity(
                ACTIVE_PARTITION,
                entity["RowKey"],
            )
            moved += 1

    remaining_entities = list(
        table_client.query_entities(
            f"PartitionKey eq '{ACTIVE_PARTITION}'"
        )
    )
    remaining_plan = build_cleanup_plan(remaining_entities)

    print(f"Moved entities: {moved}")
    print(f"Recovery partition: {args.backup_partition}")
    print(f"Remaining duplicate GroupMe IDs: {len(remaining_plan)}")
    return 0 if not remaining_plan else 1


if __name__ == "__main__":
    raise SystemExit(main())
