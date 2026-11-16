"""Manual retention cleanup requires an administrator and reports failures."""
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth import dependencies as auth
from app.routers.responders import router


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(auth, 'is_testing', False)
    application = FastAPI()
    application.include_router(router)
    return application, TestClient(application, raise_server_exceptions=False)


@pytest.mark.parametrize('user,status', [(None, 401), ({'auth_type': 'local', 'is_admin': False}, 403)])
def test_cleanup_denies_unauthorized_requests(api, user, status):
    application, client = api
    if user is not None:
        application.dependency_overrides[auth.require_auth] = lambda: user
    with patch('app.retention_scheduler.run_retention_cleanup_now', new_callable=AsyncMock) as cleanup:
        result = client.post('/api/retention/cleanup')
    assert result.status_code == status
    cleanup.assert_not_called()


def test_admin_cleanup_awaits_result(api):
    application, client = api
    application.dependency_overrides[auth.require_auth] = lambda: {'auth_type': 'local', 'is_admin': True}
    with patch('app.retention_scheduler.run_retention_cleanup_now', new_callable=AsyncMock, return_value={'active': 2, 'deleted': 1}) as cleanup:
        result = client.post('/api/retention/cleanup')
    assert result.status_code == 200
    assert result.json()['purged'] == {'active': 2, 'deleted': 1}
    cleanup.assert_awaited_once()


def test_cleanup_failure_returns_safe_error(api):
    application, client = api
    application.dependency_overrides[auth.require_auth] = lambda: {'auth_type': 'local', 'is_admin': True}
    with patch('app.retention_scheduler.run_retention_cleanup_now', new_callable=AsyncMock, side_effect=RuntimeError('synthetic-private-provider-details')):
        result = client.post('/api/retention/cleanup')
    assert result.status_code == 500
    assert result.json() == {'detail': 'Retention cleanup failed'}
