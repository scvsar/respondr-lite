from unittest.mock import patch
from fastapi import HTTPException
import pytest
from app.routers.responders import create_responder, update_responder, ResponderUpdate
from fastapi.testclient import TestClient
from app import app
from app.auth.dependencies import require_admin


@pytest.mark.asyncio
async def test_manual_creation_does_not_report_failed_save_as_success():
    with patch('app.routers.responders.add_message',return_value=False):
        with pytest.raises(HTTPException) as error:
            await create_responder({'name':'Synthetic User'}, {})
    assert error.value.status_code==500


@pytest.mark.asyncio
async def test_manual_status_is_saved():
    with patch('app.routers.responders.add_message',return_value=True) as save:
        await create_responder({'name':'Synthetic User','arrival_status':'Cancelled','eta':'15:00'}, {})
    record=save.call_args.args[0]
    assert record['arrival_status']==record['raw_status']=='Cancelled'
    assert record['eta_timestamp_utc'] is None
    assert record['minutes_until_arrival'] is None


@pytest.mark.asyncio
async def test_manual_cancellation_clears_all_eta_fields():
    with (patch('app.routers.responders.update_message',return_value=True) as save,
          patch('app.routers.responders.get_messages',return_value=[{'id':'synthetic-1'}])):
        await update_responder('synthetic-1',ResponderUpdate(arrival_status='Cancelled'),{})
    updates=save.call_args.args[1]
    assert updates['eta_timestamp_utc'] is None
    assert updates['minutes_until_arrival'] is None
    assert updates['eta']=='Unknown'


@pytest.mark.asyncio
async def test_editable_fields_are_saved_and_source_is_preserved():
    original={'id':'source-1','groupme_id':'external-1','name':'Synthetic User',
              'text':'Original reply','group_id':'original-group','created_at':1,
              'timestamp':'2026-01-01 10:00:00'}
    edit=ResponderUpdate(text='Corrected reply',team='Corrected Team',group_id='corrected-group',timestamp='2026-01-02T18:00:00Z')
    with (patch('app.routers.responders.get_messages',return_value=[original]),
          patch('app.routers.responders.update_message',return_value=True) as save):
        await update_responder('source-1',edit,{})
    updates=save.call_args.args[1]
    assert updates['text']=='Corrected reply'
    assert updates['team']=='Corrected Team'
    assert updates['group_id']=='corrected-group'
    assert updates['timestamp_utc']=='2026-01-02T18:00:00+00:00'
    assert updates['original_text']=='Original reply'
    assert updates['original_group_id']=='original-group'
    assert updates['original_created_at']==1


@pytest.mark.parametrize('field', ['timestamp','eta_timestamp'])
@pytest.mark.asyncio
async def test_invalid_manual_timestamp_is_rejected(field):
    with patch('app.routers.responders.add_message') as save:
        with pytest.raises(HTTPException) as error:
            await create_responder({'name':'Synthetic User',field:'invalid-date'}, {})
    assert error.value.status_code==400
    save.assert_not_called()


def test_create_schema_rejects_missing_identity():
    previous=app.dependency_overrides.copy()
    app.dependency_overrides[require_admin]=lambda: {}
    try:
        with patch('app.routers.responders.add_message') as save:
            response=TestClient(app).post('/api/responders',json={'text':'Synthetic reply'})
        assert response.status_code==422
        save.assert_not_called()
    finally:
        app.dependency_overrides=previous
