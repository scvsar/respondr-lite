from unittest.mock import patch
import pytest
from app.routers.responders import get_current_status, get_responders
from app.routers.webhook import WebhookMessage, webhook_handler


def row(user, name, group='group-1', timestamp='2026-01-01T00:00:00Z'):
    return dict(id=user+timestamp, user_id=user, name=name, group_id=group,
                timestamp_utc=timestamp, text='Responding', arrival_status='Responding', eta='Unknown')


@pytest.mark.asyncio
async def test_same_name_different_users_remain_separate():
    rows=[row('user-1','Synthetic Name'),row('user-2','Synthetic Name')]
    with patch('app.routers.responders.get_messages', return_value=rows):
        assert len(await get_current_status(None, {})) == 2


@pytest.mark.asyncio
async def test_name_change_does_not_create_another_responder():
    rows=[row('user-1','Old Name'),row('user-1','New Name', timestamp='2026-01-01T01:00:00Z')]
    with patch('app.routers.responders.get_messages', return_value=rows):
        result=await get_current_status(None, {})
    assert len(result)==1
    assert result[0]['name']=='New Name'


@pytest.mark.asyncio
async def test_status_is_scoped_to_group():
    rows=[row('user-1','Synthetic Name'),row('user-1','Synthetic Name','group-2')]
    with patch('app.routers.responders.get_messages', return_value=rows):
        assert len(await get_current_status(None, {}))==2


@pytest.mark.asyncio
async def test_legacy_name_uses_unique_known_identity():
    old=row('user-1','Synthetic Name'); old.pop('user_id')
    rows=[old,row('user-1','Synthetic Name',timestamp='2026-01-01T01:00:00Z')]
    with patch('app.routers.responders.get_messages',return_value=rows):
        assert len(await get_current_status(None, {}))==1
        all_rows=await get_responders(None, {})
    assert all_rows[0]['responder_key']==all_rows[1]['responder_key']


@pytest.mark.asyncio
async def test_old_mission_eta_is_not_inherited():
    message=WebhookMessage(id='new-source',user_id='user-1',name='Synthetic Name',group_id='group-1',text='Responding',created_at=1794797000)
    history=[dict(row('user-1','Synthetic Name'), created_at=1794797000-86400,
                  eta_timestamp_utc='2026-01-01T00:00:00Z',raw_status='Responding')]
    parsed=dict(vehicle='Unknown',eta='Unknown',eta_timestamp=None,eta_timestamp_utc=None,
                minutes_until_arrival=None,raw_status='Responding',status_source='LLM',status_confidence=0.9)
    with (patch('app.routers.webhook.get_messages',return_value=history),
          patch('app.routers.webhook.get_deleted_messages',return_value=[]),
          patch('app.routers.webhook.add_message',return_value=True),
          patch('app.routers.webhook.extract_details_from_text',return_value=parsed) as extract):
        await webhook_handler(message,None,False)
    assert extract.call_args.kwargs['prev_eta_iso'] is None


@pytest.mark.asyncio
async def test_equal_time_cancellation_wins_over_response():
    cancelled = dict(row('user-1','Synthetic Name'), arrival_status='Cancelled')
    responding = row('user-1','Synthetic Name')
    with patch('app.routers.responders.get_messages',return_value=[cancelled,responding]):
        result=await get_current_status(None,{})
    assert result[0]['arrival_status']=='Cancelled'


@pytest.mark.asyncio
async def test_legacy_local_timestamp_orders_against_utc():
    local = row('user-1', 'Synthetic Name')
    local.pop('timestamp_utc')
    local['timestamp']='2026-01-01 10:00:00'
    utc = row('user-1','Synthetic Name', timestamp='2026-01-01T15:00:00Z')
    utc['id']='utc'
    with patch('app.routers.responders.get_messages',return_value=[local,utc]):
        result=await get_current_status(None,{})
    assert result[0]['id']==local['id']
