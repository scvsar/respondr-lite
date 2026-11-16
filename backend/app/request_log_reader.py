"""Read a bounded result from the recent request log window."""
import heapq
import os
from datetime import datetime, timedelta, timezone

from azure.data.tables import TableServiceClient

from .utils import parse_datetime_like


def read_recent_request_logs(now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(hours=24)
    partitions = [current.strftime('%Y%m%d'), cutoff.strftime('%Y%m%d')]
    table_name = os.getenv('REQUEST_LOG_TABLE', 'RequestLogs')
    connection = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
    if not connection:
        raise RuntimeError('Request logging not configured')
    start = cutoff.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    end = current.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    with TableServiceClient.from_connection_string(connection, connection_timeout=5, read_timeout=15) as service:
        table = service.get_table_client(table_name)

        def records():
            for partition in dict.fromkeys(partitions):
                query = "PartitionKey eq @partition and timestamp ge @start and timestamp le @end"
                for entity in table.query_entities(
                    query, parameters={'partition': partition, 'start': start, 'end': end}, results_per_page=100,
                ):
                    row = dict(entity)
                    stamp = parse_datetime_like(row.get('timestamp'))
                    if stamp is not None and cutoff <= stamp <= current:
                        yield stamp.timestamp(), str(row.get('RowKey', '')), row

        # Table Storage returns ascending keys. A page limit would select old rows.
        latest = heapq.nlargest(100, records(), key=lambda record: record[:2])
    logs = [record[2] for record in latest]
    return {'table_name': table_name, 'partition_keys_checked': partitions, 'log_count': len(logs), 'logs': logs}
