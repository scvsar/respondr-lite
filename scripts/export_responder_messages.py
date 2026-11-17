"""Export recent raw responder messages as JSON Lines."""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from azure.core.credentials import AzureNamedKeyCredential
from azure.data.tables import TableClient
from dotenv import load_dotenv


ACCOUNT_ENV = "RESPONDR_STORAGE_ACCOUNT_NAME"
KEY_ENV = "RESPONDR_STORAGE_ACCOUNT_KEY"
TABLE_ENV = "RESPONDR_STORAGE_TABLE_NAME"
TIMEZONE_ENV = "RESPONDR_MESSAGE_TIMEZONE"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def export_messages(
    table: TableClient, cutoff: datetime, now: datetime, legacy_zone: ZoneInfo
) -> None:
    # Azure's Timestamp is the last write time. Use message time for the export.
    for entity in table.list_entities():
        value = entity.get("timestamp_utc") or entity.get("timestamp")
        if not isinstance(value, str):
            continue
        try:
            stamp = datetime.fromisoformat(value)
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=legacy_zone)
        if cutoff <= stamp.astimezone(timezone.utc) <= now:
            print(json.dumps(dict(entity), default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be a positive integer")

    now = datetime.now(timezone.utc)
    try:
        cutoff = now - timedelta(days=args.days)
    except OverflowError:
        parser.error("--days is too large")

    load_dotenv(ENV_FILE, override=False)
    required_vars = (ACCOUNT_ENV, KEY_ENV, TABLE_ENV, TIMEZONE_ENV)
    missing = [name for name in required_vars if not os.environ.get(name)]
    if missing:
        parser.error(f"Set these variables in the repository root .env file: {', '.join(missing)}")

    account = os.environ[ACCOUNT_ENV]
    legacy_zone = ZoneInfo(os.environ[TIMEZONE_ENV])
    with TableClient(
        endpoint=f"https://{account}.table.core.windows.net",
        table_name=os.environ[TABLE_ENV],
        credential=AzureNamedKeyCredential(account, os.environ[KEY_ENV]),
        connection_timeout=10,
        read_timeout=30,
    ) as table:
        export_messages(table, cutoff, now, legacy_zone)


if __name__ == "__main__":
    main()
