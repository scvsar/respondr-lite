"""Local-user storage must fail closed and keep account operations usable."""
import threading
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import ResourceNotFoundError

from app import local_auth as auth


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(auth, 'ENABLE_LOCAL_AUTH', True)
    monkeypatch.setattr(auth, 'is_testing', False)
    monkeypatch.setattr(auth, '_local_users_memory_store', {})
    monkeypatch.setenv('LOCAL_AUTH_STORAGE_BACKEND', 'azure_table')
    for name in ['AZURE_STORAGE_CONNECTION_STRING', 'AZURE_STORAGE_ACCOUNT', 'AZURE_STORAGE_KEY']:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_azure_outage_cannot_create_an_account_in_memory(monkeypatch):
    monkeypatch.setenv('AZURE_STORAGE_CONNECTION_STRING', 'synthetic-configuration')
    with patch('app.local_auth.TableClient.from_connection_string', side_effect=RuntimeError('synthetic outage')):
        with pytest.raises(RuntimeError):
            await auth.create_local_user('synthetic', 'password', 'synthetic@example.test', 'Synthetic User')
    assert auth._local_users_memory_store == {}


def test_no_implicit_memory_mode_when_storage_is_missing(monkeypatch):
    for name in ['AZURE_STORAGE_CONNECTION_STRING', 'AZURE_STORAGE_ACCOUNT', 'AZURE_STORAGE_KEY']:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError):
        auth.get_table_client('LocalUsers')


@pytest.mark.asyncio
async def test_explicit_memory_mode_supports_account_lifecycle(monkeypatch):
    monkeypatch.setenv('LOCAL_AUTH_STORAGE_BACKEND', 'memory')
    assert await auth.create_local_user('synthetic', 'old-password', 'synthetic@example.test', 'Synthetic User')
    assert not await auth.create_local_user('synthetic', 'duplicate', 'synthetic@example.test', 'Synthetic User')
    assert (await auth.verify_local_user('synthetic@example.test', 'old-password')).username == 'synthetic'
    assert await auth.update_local_user_password('synthetic', 'new-password')
    assert await auth.verify_local_user('synthetic', 'old-password') is None
    assert (await auth.verify_local_user('synthetic', 'new-password')).username == 'synthetic'
    assert [user.username for user in await auth.list_local_users()] == ['synthetic']
    assert await auth.delete_local_user('synthetic')
    assert await auth.get_local_user('synthetic') is None


@pytest.mark.asyncio
async def test_local_user_reads_run_outside_event_loop(monkeypatch):
    loop_thread = threading.get_ident()
    calls = []
    table = MagicMock()
    def get_client(_):
        calls.append(threading.get_ident())
        return table
    def get_entity(*_):
        calls.append(threading.get_ident())
        return {'RowKey':'synthetic', 'email':'synthetic@example.test'}
    monkeypatch.setattr(auth, 'get_table_client', get_client)
    table.get_entity.side_effect = get_entity
    assert (await auth.get_local_user('synthetic')).username == 'synthetic'
    assert all(thread != loop_thread for thread in calls)


@pytest.mark.asyncio
async def test_email_lookup_does_not_interpolate_input(monkeypatch):
    table = MagicMock()
    table.query_entities.return_value = []
    monkeypatch.setattr(auth, 'get_table_client', lambda _: table)
    supplied = "synthetic@example.test' or RowKey ne ''"
    assert await auth.get_local_user_by_email(supplied) is None
    query = table.query_entities.call_args_list[0]
    assert supplied not in query.args[0]
    assert supplied in query.kwargs['parameters'].values()


def test_non_boolean_admin_storage_value_cannot_grant_admin():
    assert auth.LocalUser.from_dict({'RowKey':'synthetic','is_admin':'False'}).is_admin is False


@pytest.mark.asyncio
async def test_password_change_does_not_replace_account_permissions(monkeypatch):
    table = MagicMock()
    table.get_entity.return_value = {'PartitionKey':'localuser','RowKey':'synthetic','is_admin':True}
    monkeypatch.setattr(auth, 'get_table_client', lambda _: table)
    assert await auth.update_local_user_password('synthetic', 'new-password')
    saved = table.update_entity.call_args.args[0]
    assert set(saved) == {'PartitionKey','RowKey','password_hash','password_salt'}
    assert table.update_entity.call_args.kwargs['mode'] == 'merge'


@pytest.mark.asyncio
async def test_email_lookup_preserves_case_insensitive_legacy_accounts(monkeypatch):
    table = MagicMock()
    table.query_entities.side_effect = [[], [{'RowKey':'synthetic','email':'Synthetic@Example.Test'}]]
    monkeypatch.setattr(auth, 'get_table_client', lambda _: table)
    assert (await auth.get_local_user_by_email('synthetic@example.test')).username == 'synthetic'


def test_login_storage_failure_returns_unavailable_without_provider_details():
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock
    from app import app
    with patch('app.routers.auth.verify_local_user', new_callable=AsyncMock, side_effect=auth.LocalAuthStorageError('synthetic-private-details')):
        response = TestClient(app).post('/api/auth/local/login', json={'username':'synthetic','password':'test-password'})
    assert response.status_code == 503
    assert response.json() == {'success':False,'error':'Local authentication unavailable'}
