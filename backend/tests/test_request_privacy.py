from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import app
from app.request_logger import RequestLogger


@pytest.mark.parametrize('testing,enabled', [(False, 'false'), (True, 'true')])
def test_request_logging_does_not_connect_when_disabled_or_testing(monkeypatch, testing, enabled):
    monkeypatch.setenv('AZURE_STORAGE_CONNECTION_STRING', 'synthetic-configuration')
    monkeypatch.setenv('ENABLE_REQUEST_LOGGING', enabled)
    monkeypatch.setattr('app.request_logger.is_testing', testing, raising=False)
    with patch('app.request_logger.TableServiceClient.from_connection_string') as connect:
        logger = RequestLogger()
    connect.assert_not_called()
    assert logger.enabled is False


def test_enabled_request_logging_initializes_fake_storage(monkeypatch):
    monkeypatch.setenv('AZURE_STORAGE_CONNECTION_STRING', 'synthetic-configuration')
    monkeypatch.setenv('ENABLE_REQUEST_LOGGING', 'true')
    monkeypatch.setattr('app.request_logger.is_testing', False)
    with patch('app.request_logger.TableServiceClient.from_connection_string') as connect:
        logger = RequestLogger()
    connect.assert_called_once()
    assert logger.enabled is True
    assert logger.table_client is connect.return_value.get_table_client.return_value


def test_logger_initialization_failure_does_not_log_provider_content(monkeypatch, caplog):
    monkeypatch.setenv('AZURE_STORAGE_CONNECTION_STRING', 'synthetic-configuration')
    monkeypatch.setenv('ENABLE_REQUEST_LOGGING', 'true')
    monkeypatch.setattr('app.request_logger.is_testing', False)
    with patch('app.request_logger.TableServiceClient.from_connection_string', side_effect=RuntimeError('synthetic-private-details')):
        assert RequestLogger().enabled is False
    assert 'synthetic-private-details' not in caplog.text


def test_api_middleware_does_not_log_authorization(caplog, capsys):
    TestClient(app).get('/api/not-a-route', headers={'Authorization': 'Bearer synthetic-secret'})
    assert 'synthetic-secret' not in caplog.text
    assert 'synthetic-secret' not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_request_log_omits_query_and_referer_credentials():
    logger = RequestLogger.__new__(RequestLogger)
    logger.enabled = True
    logger._insert_entity = AsyncMock()
    request = Request({'type': 'http', 'method': 'GET', 'scheme': 'https',
                       'path': '/wake', 'query_string': b'k=synthetic-secret',
                       'headers': [(b'host', b'example.test'),
                                   (b'referer', b'https://example.test/?token=synthetic-secret')]})
    pending = []
    with patch('app.request_logger.asyncio.create_task', side_effect=pending.append):
        await logger.log_request(request)
    for task in pending:
        await task
    entity = logger._insert_entity.call_args.args[0]
    assert 'synthetic-secret' not in str(entity)
    assert entity['path'] == '/wake'
