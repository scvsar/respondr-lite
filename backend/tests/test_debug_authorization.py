from unittest.mock import patch
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app.routers.webhook import WebhookMessage, webhook_handler


def message():
    return WebhookMessage(id='source-1',group_id='synthetic-group',name='Synthetic User',text='Responding',created_at=1794797000,debug_sys_prompt='Synthetic override')


def request():
    return Request({'type':'http','method':'POST','path':'/webhook','headers':[(b'x-auth-request-email',b'admin@example.test')]})


@pytest.mark.asyncio
@pytest.mark.parametrize('code',[401,403])
async def test_debug_rejects_before_any_data_processing(code):
    auth_error=HTTPException(status_code=code,detail='Rejected')
    with (patch('app.routers.webhook.require_auth',side_effect=auth_error),
          patch('app.routers.webhook.get_messages',return_value=[]) as history,
          patch('app.routers.webhook.get_deleted_messages',return_value=[]),
          patch('app.routers.webhook.extract_details_from_text') as extract,
          patch('app.routers.webhook.add_message',return_value=True) as save):
        with pytest.raises(HTTPException) as error:
            await webhook_handler(message(),request(),True)
    assert error.value.status_code==code
    history.assert_not_called()
    extract.assert_not_called()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_authenticated_admin_can_apply_debug_overrides_without_proxy_headers():
    parsed=dict(vehicle='Unknown',eta='Unknown',eta_timestamp=None,eta_timestamp_utc=None,
                minutes_until_arrival=None,arrival_status='Responding',raw_status='Responding',status_source='LLM',status_confidence=0.8)
    req=Request({'type':'http','method':'POST','path':'/webhook','headers':[]})
    with (patch('app.routers.webhook.require_auth',return_value={'auth_type':'local','is_admin':True}),
          patch('app.routers.webhook.require_admin',return_value={}),
          patch('app.routers.webhook.get_messages',return_value=[]),
          patch('app.routers.webhook.get_deleted_messages',return_value=[]),
          patch('app.routers.webhook.extract_details_from_text',return_value=parsed) as extract,
          patch('app.routers.webhook.add_message',return_value=True)):
        result=await webhook_handler(message(),req,True)
    assert result['status']=='ok'
    assert extract.call_args.kwargs['sys_prompt_override']=='Synthetic override'
