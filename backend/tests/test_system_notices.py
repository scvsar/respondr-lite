from unittest.mock import patch

import pytest

from app.message_policy import responder_messages
from app.routers.webhook import WebhookMessage, webhook_handler
from app.routers.responders import get_responders, get_current_status


def test_legacy_notice_filter_preserves_ordinary_messages():
    ordinary = {'name': 'Synthetic User', 'text': 'A message was deleted.'}
    notice = {'name': 'GroupMe', 'text': 'A message was deleted.'}
    assert responder_messages([notice, ordinary]) == [ordinary]
    assert responder_messages([{'system': 'True'}, {'sender_type': 'system'}]) == []


@pytest.mark.asyncio
async def test_system_notice_is_preserved_without_extraction_on_retry():
    message = WebhookMessage(id='notice-1', group_id='synthetic-group',
                             name='GroupMe', text='A message was deleted.',
                             created_at=1784844000, system=True)
    with (patch('app.routers.webhook.add_message', return_value=True) as save,
          patch('app.routers.webhook.extract_details_from_text') as extract,
          patch('app.routers.webhook.get_messages') as history):
        for _ in range(2):
            assert await webhook_handler(message, None, False) == {'status': 'system_notice'}
    extract.assert_not_called()
    history.assert_not_called()
    first, second = [call.args[0] for call in save.call_args_list]
    assert first == second
    assert first['text'] == message.text
    assert first['groupme_id'] == 'notice-1'
    assert first['system'] is True
    assert first['eta'] == first['vehicle'] == 'Unknown'
    assert responder_messages([first]) == []


@pytest.mark.parametrize('text', [
    'A message was deleted.',
    'Synthetic Admin removed Synthetic Member from the group.',
    'Synthetic Admin added Synthetic Member to the group.',
    'Synthetic Member left the group.',
])
@pytest.mark.asyncio
async def test_both_responder_apis_exclude_legacy_notices(text):
    notice = {'name': 'GroupMe', 'text': text}
    with patch('app.routers.responders.get_messages', return_value=[notice]):
        assert await get_responders(since=None, _={}) == []
        assert await get_current_status(since=None, _={}) == []
