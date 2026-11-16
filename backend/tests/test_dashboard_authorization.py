"""Legacy HTML dashboards must enforce responder access policy."""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth import dependencies as auth
from app.routers.dashboard import router


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(auth, 'is_testing', False)
    application = FastAPI()
    application.include_router(router)
    return application, TestClient(application)


@pytest.mark.parametrize('path', ['/dashboard', '/deleted-dashboard'])
def test_dashboards_reject_anonymous_requests_before_storage(api, path):
    _, client = api
    with patch('app.routers.dashboard.get_messages') as active, patch('app.routers.dashboard.get_deleted_messages') as deleted:
        assert client.get(path).status_code == 401
    active.assert_not_called()
    deleted.assert_not_called()


def test_non_admin_can_read_active_but_not_deleted_dashboard(api):
    application, client = api
    application.dependency_overrides[auth.require_auth] = lambda: {'auth_type': 'local', 'is_admin': False}
    with patch('app.routers.dashboard.get_messages', return_value=[]), patch('app.routers.dashboard.get_deleted_messages') as deleted:
        assert client.get('/dashboard').status_code == 200
        assert client.get('/deleted-dashboard').status_code == 403
    deleted.assert_not_called()


def test_admin_can_read_deleted_dashboard(api):
    application, client = api
    application.dependency_overrides[auth.require_auth] = lambda: {'auth_type': 'local', 'is_admin': True}
    with patch('app.routers.dashboard.get_deleted_messages', return_value=[]):
        assert client.get('/deleted-dashboard').status_code == 200
