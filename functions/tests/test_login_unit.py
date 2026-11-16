import json
from unittest.mock import patch
import hashlib
import jwt
import azure.functions as func
import pytest
from functions import local_login as login


def request(body):
    return func.HttpRequest(method='POST', url='https://example.test/api/local_login',
                           headers={}, params={}, body=json.dumps(body).encode())


@pytest.mark.parametrize('body', [[], None, 'text', {'email': 1, 'password': 2}])
def test_login_rejects_malformed_payload(body, monkeypatch):
    monkeypatch.setenv('ENABLE_LOCAL_AUTH', 'true')
    assert login.main(request(body)).status_code == 400


def test_login_requires_secret(monkeypatch):
    monkeypatch.setenv('ENABLE_LOCAL_AUTH', 'true')
    monkeypatch.setenv('AzureWebJobsStorage', 'synthetic')
    monkeypatch.delenv('LOCAL_AUTH_SECRET_KEY', raising=False)
    monkeypatch.delenv('LOCAL_AUTH_SECRET_FALLBACK', raising=False)
    with patch.object(login, 'TableClient') as table:
        assert login.main(request({'email': 'user@example.test', 'password': 'test'})).status_code == 503
    table.from_connection_string.assert_not_called()


def test_disabled_login_does_not_access_storage(monkeypatch):
    monkeypatch.setenv('ENABLE_LOCAL_AUTH', 'false')
    with patch.object(login, 'TableClient') as table:
        assert login.main(request({'email': 'user@example.test', 'password': 'test'})).status_code == 403
    table.from_connection_string.assert_not_called()


def test_valid_login_issues_compatible_token(monkeypatch):
    secret = 'synthetic-test-signing-secret-that-is-long-enough'
    monkeypatch.setenv('ENABLE_LOCAL_AUTH', 'true')
    monkeypatch.setenv('LOCAL_AUTH_SECRET_KEY', secret)
    monkeypatch.setenv('AzureWebJobsStorage', 'synthetic')
    user = {'RowKey': 'synthetic-user', 'email': 'user@example.test',
            'password_salt': 'synthetic-salt', 'is_admin': False,
            'password_hash': hashlib.pbkdf2_hmac('sha256', b'test', b'synthetic-salt', 100000).hex()}
    with patch.object(login, 'TableClient') as table:
        table.from_connection_string.return_value.query_entities.return_value = [user]
        response = login.main(request({'email': 'user@example.test', 'password': 'test'}))
    assert response.status_code == 200
    token = json.loads(response.get_body())['token']
    claims = jwt.decode(token, secret, algorithms=['HS256'], issuer='local', options={'require':['exp','username','iss']})
    assert claims['auth_type'] == 'local'
    assert claims['is_admin'] is False
