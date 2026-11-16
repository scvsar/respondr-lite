import json
import logging
from unittest.mock import MagicMock, patch

import azure.functions as func
import pytest

from functions import groupme_ingest as ingest


def request(payload=None, headers=None):
    return func.HttpRequest(method='POST', url='https://example.test/api/groupme_ingest?k=secret-query',
                            headers=headers or {}, params={}, body=json.dumps(payload).encode())


def payload():
    return dict(name='Synthetic User', text='Responding, ETA 30 minutes', created_at=1794797000,
                group_id='test-group', id='test-id', user_id='test-user', sender_id='test-user',
                sender_type='user', source_guid='test-id')


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.delenv('WEBHOOK_API_KEY', raising=False)
    monkeypatch.setenv('ALLOWED_GROUPME_GROUP_IDS', 'test-group')
    monkeypatch.setenv('STORAGE_QUEUE_NAME', 'test-queue')
    monkeypatch.setenv('AzureWebJobsStorage', 'synthetic-connection')
    monkeypatch.delenv('CONTAINER_APP_WAKE_URL', raising=False)


def test_no_auth_policy_fails_closed(monkeypatch):
    monkeypatch.delenv('ALLOWED_GROUPME_GROUP_IDS')
    with patch.object(ingest, 'QueueClient') as queue:
        assert ingest.main(request(payload())).status_code == 503
    queue.from_connection_string.assert_not_called()


@pytest.mark.parametrize('body', [[], None, 'hello', 7, {'text': 'missing required fields'}])
def test_malformed_payloads_return_stable_error(body):
    response = ingest.main(request(body))
    assert response.status_code == 400
    assert response.get_body() == b'Invalid payload'


def test_rejected_group_is_not_logged_or_enqueued():
    body = payload(); body['group_id'] = 'other-group'
    with patch.object(ingest, 'log_payload') as log, patch.object(ingest, 'QueueClient') as queue:
        assert ingest.main(request(body)).status_code == 401
    log.assert_not_called()
    queue.from_connection_string.assert_not_called()


def test_success_does_not_log_credentials_or_message(caplog):
    with patch.object(ingest, 'QueueClient'), patch.object(ingest, 'log_payload'), caplog.at_level(logging.INFO):
        assert ingest.main(request(payload(), {'Authorization': 'secret-header'})).status_code == 200
    assert 'secret-query' not in caplog.text
    assert 'secret-header' not in caplog.text
    assert payload()['text'] not in caplog.text


def test_queue_failure_has_minimal_error():
    with patch.object(ingest.QueueClient, 'from_connection_string', side_effect=RuntimeError('secret-provider')):
        response = ingest.main(request(payload()))
    assert response.status_code == 500
    assert response.get_body() == b'Queue unavailable'


def test_wake_failure_does_not_undo_enqueue(monkeypatch):
    monkeypatch.setenv('CONTAINER_APP_WAKE_URL', 'https://example.test/wake')
    with patch.object(ingest, 'QueueClient') as queue, patch.object(ingest.urllib.request, 'urlopen', side_effect=TimeoutError):
        assert ingest.main(request(payload())).status_code == 200
    queue.from_connection_string.return_value.send_message.assert_called_once()


@pytest.mark.parametrize('token,expected', [('synthetic-key', 200), ('wrong', 401), ('', 401)])
def test_webhook_key_policy(monkeypatch, token, expected):
    monkeypatch.setenv('WEBHOOK_API_KEY', 'synthetic-key')
    with patch.object(ingest, 'QueueClient') as queue:
        response = ingest.main(request(payload(), {'X-Webhook-Token': token}))
    assert response.status_code == expected
    assert queue.from_connection_string.called == (expected == 200)


def test_invalid_json_has_minimal_error():
    req = func.HttpRequest(method='POST', url='https://example.test/api/groupme_ingest',
                           headers={}, params={}, body=b'{bad-json')
    response = ingest.main(req)
    assert response.status_code == 400
    assert response.get_body() == b'Invalid JSON'
