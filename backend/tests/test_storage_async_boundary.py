"""Storage calls must not block the API or queue event loop."""
import threading
from unittest.mock import patch

from fastapi import HTTPException
import pytest

from app.routers import responders, webhook


@pytest.mark.asyncio
@pytest.mark.parametrize('route,args,results', [
    ('get_responders', (None, {}), {'get_messages': []}),
    ('get_current_status', (None, {}), {'get_messages': []}),
    ('create_responder', (responders.ResponderCreate(name='Synthetic User'), {}), {'add_message': True}),
    ('update_responder', ('one', responders.ResponderUpdate(text='Synthetic correction'), {}), {'get_messages': [{'id':'one'}], 'update_message': True}),
    ('delete_responder', ('one', {}), {'delete_message': True}),
    ('bulk_delete_responders', (responders.BulkDeleteRequest(ids=['one']), {}), {'bulk_delete_messages': 1}),
    ('clear_all_responders', ({},), {'clear_all_messages': 1}),
    ('get_deleted_responders', ({},), {'get_deleted_messages': []}),
    ('undelete_responder', (responders.UndeleteRequest(message_id='one'), {}), {'undelete_message': True, 'get_messages': [{'id':'one'}]}),
    ('permanently_delete_responder', ('one', {}), {'permanently_delete_message': True}),
    ('clear_all_deleted', ({},), {'clear_all_deleted_messages': 1}),
    ('get_storage_status', ({},), {'get_storage_info': {}}),
])
async def test_storage_runs_outside_event_loop(monkeypatch, route, args, results):
    loop_thread = threading.get_ident()
    calls = []
    def fake(result):
        def operation(*args, **kwargs):
            calls.append(threading.get_ident())
            return result
        return operation
    for name, result in results.items():
        monkeypatch.setattr(responders, name, fake(result))
    await getattr(responders, route)(*args)
    assert calls
    assert all(thread != loop_thread for thread in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('system', [False, True])
async def test_worker_storage_does_not_block_visibility_renewal(monkeypatch, system):
    loop_thread = threading.get_ident()
    calls = []
    def read():
        calls.append(threading.get_ident())
        return []
    def save(_):
        calls.append(threading.get_ident())
        return True
    monkeypatch.setattr(webhook, 'get_messages', read)
    monkeypatch.setattr(webhook, 'get_deleted_messages', read)
    monkeypatch.setattr(webhook, 'add_message', save)
    parsed = dict(vehicle='Unknown', eta='Unknown', eta_timestamp=None, eta_timestamp_utc=None,
                  minutes_until_arrival=None, raw_status='Responding', status_source='LLM', status_confidence=0.8)
    message = webhook.WebhookMessage(id='source', group_id='synthetic-group', name='Synthetic User', text='Responding', system=system, created_at=1794797000)
    with patch.object(webhook, 'extract_details_from_text', return_value=parsed):
        await webhook.webhook_handler(message, None, False)
    assert calls
    assert all(thread != loop_thread for thread in calls)


@pytest.mark.asyncio
async def test_duplicate_check_failure_does_not_overwrite_a_record():
    message = webhook.WebhookMessage(id='source', group_id='synthetic-group', name='Synthetic User', text='Responding', created_at=1794797000)
    with (patch.object(webhook, 'get_deleted_messages', return_value=[]),
          patch.object(webhook, 'get_messages', side_effect=RuntimeError('synthetic outage')),
          patch.object(webhook, 'add_message') as save,
          patch.object(webhook, 'extract_details_from_text') as extract):
        with pytest.raises(HTTPException) as caught:
            await webhook.webhook_handler(message, None, False)
    assert caught.value.status_code == 500
    save.assert_not_called()
    extract.assert_not_called()
