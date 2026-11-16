"""Diagnostics must return recent logs and safe errors."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
import pytest

from app.routers.responders import get_request_logs, get_request_logs_debug


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', [get_request_logs, get_request_logs_debug])
async def test_request_log_failure_does_not_expose_provider_details(monkeypatch, endpoint):
    monkeypatch.setenv('AZURE_STORAGE_CONNECTION_STRING', 'synthetic-configuration')
    with patch('azure.data.tables.TableServiceClient.from_connection_string', side_effect=RuntimeError('synthetic-private-provider-details')):
        with pytest.raises(HTTPException) as caught:
            await endpoint({})
    assert caught.value.status_code == 500
    assert 'synthetic-private-provider-details' not in caught.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', [get_request_logs, get_request_logs_debug])
async def test_request_logs_not_configured_is_unavailable(monkeypatch, endpoint):
    monkeypatch.delenv('AZURE_STORAGE_CONNECTION_STRING', raising=False)
    with pytest.raises(HTTPException) as caught:
        await endpoint({})
    assert caught.value.status_code == 503


@pytest.mark.asyncio
async def test_request_logs_return_newest_hundred_from_today(monkeypatch):
    monkeypatch.setenv('AZURE_STORAGE_CONNECTION_STRING', 'synthetic-configuration')
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # These rows use the chronological order that Table Storage returns.
    rows = [{'RowKey': str(index), 'timestamp': (midnight + (now - midnight) * index / 150).isoformat(), 'method': 'GET'}
            for index in range(150)]
    table = MagicMock()
    table.query_entities.side_effect = [rows, []]
    service = MagicMock()
    service.get_table_client.return_value = table
    service.__enter__.return_value = service
    with patch('azure.data.tables.TableServiceClient.from_connection_string', return_value=service):
        result = await get_request_logs({})
    assert len(result) == 100
    assert result[0]['RowKey'] == '149'
    assert result[-1]['RowKey'] == '50'


def test_reader_enforces_rolling_window_and_closes_client(monkeypatch):
    from app.request_log_reader import read_recent_request_logs
    monkeypatch.setenv('AZURE_STORAGE_CONNECTION_STRING', 'synthetic-configuration')
    now = datetime(2026, 11, 16, 6, tzinfo=timezone.utc)
    rows = [
        {'RowKey': 'old', 'timestamp': (now - timedelta(hours=25)).isoformat()},
        {'RowKey': 'boundary', 'timestamp': (now - timedelta(hours=24)).isoformat()},
        {'RowKey': 'recent', 'timestamp': (now - timedelta(hours=1)).isoformat()},
        {'RowKey': 'future', 'timestamp': (now + timedelta(hours=1)).isoformat()},
        {'RowKey': 'invalid', 'timestamp': 'invalid'},
    ]
    table, service = MagicMock(), MagicMock()
    table.query_entities.side_effect = [[], rows]
    service.get_table_client.return_value = table
    service.__enter__.return_value = service
    with patch('azure.data.tables.TableServiceClient.from_connection_string', return_value=service):
        result = read_recent_request_logs(now)
    assert [row['RowKey'] for row in result['logs']] == ['recent', 'boundary']
    assert result['partition_keys_checked'] == ['20261116', '20261115']
    assert all(call.kwargs['parameters']['start'] == '2026-11-15T06:00:00Z' for call in table.query_entities.call_args_list)
    service.__exit__.assert_called_once()
