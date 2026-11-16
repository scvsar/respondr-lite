from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest
from fastapi import HTTPException
from app.auth import dependencies as auth
from app.local_auth import verify_session_token

TENANT = '11111111-1111-4111-8111-111111111111'
SECRET = 'synthetic-test-secret-that-is-long-enough'

@pytest.fixture
def entra(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = SimpleNamespace(key=private.public_key(), _jwk_data={'issuer': 'https://login.microsoftonline.com/{tenantid}/v2.0'})
    client = MagicMock(); client.get_signing_key_from_jwt.return_value = key
    monkeypatch.setattr(auth, 'jwks_client', client)
    monkeypatch.setattr(auth, 'TENANT_ID', 'organizations')
    monkeypatch.setattr(auth, 'API_AUDIENCE', 'api://synthetic-api')
    monkeypatch.setattr(auth, 'AAD_CLIENT_ID', '')
    monkeypatch.setenv('ALLOWED_EMAIL_DOMAINS', 'example.test')
    claims = dict(iss=f'https://login.microsoftonline.com/{TENANT}/v2.0', tid=TENANT,
                  aud='api://synthetic-api', sub='synthetic-user', ver='2.0', scp='access_as_user',
                  preferred_username='user@example.test', exp=datetime.now(timezone.utc)+timedelta(minutes=5))
    return private, claims, key


def test_valid_entra_token(entra):
    private, claims, _ = entra
    assert auth.require_auth(None, jwt.encode(claims, private, algorithm='RS256'))['sub'] == 'synthetic-user'


@pytest.mark.parametrize('change', ['issuer','tenant','audience','missing-exp','missing-email','key-issuer','missing-config','expired','scope','signature'])
def test_invalid_entra_token_rejected(entra, monkeypatch, change):
    private, claims, key = entra
    if change == 'issuer': claims['iss'] = 'https://evil.example/'
    if change == 'tenant': monkeypatch.setattr(auth, 'TENANT_ID', '22222222-2222-4222-8222-222222222222')
    if change == 'audience': claims['aud'] = 'another-api'
    if change == 'missing-exp': del claims['exp']
    if change == 'missing-email': del claims['preferred_username']
    if change == 'key-issuer': key._jwk_data['issuer'] = 'https://evil.example/'
    if change == 'missing-config': monkeypatch.setattr(auth, 'API_AUDIENCE', None)
    if change == 'expired': claims['exp'] = datetime.now(timezone.utc)-timedelta(minutes=1)
    if change == 'scope': claims['scp'] = 'unrelated_scope'
    if change == 'signature': key.key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    with pytest.raises(HTTPException):
        auth.require_auth(None, jwt.encode(claims, private, algorithm='RS256'))


@pytest.mark.parametrize('change', ['disabled','missing-exp','missing-issuer','wrong-issuer','expired'])
def test_invalid_local_tokens_rejected(monkeypatch, change):
    monkeypatch.setattr(auth, 'ENABLE_LOCAL_AUTH', change != 'disabled', raising=False)
    monkeypatch.setattr(auth, 'LOCAL_AUTH_SECRET_KEY', SECRET)
    claims = dict(iss='local', username='synthetic-user', exp=datetime.now(timezone.utc)+timedelta(minutes=5))
    if change == 'missing-exp': del claims['exp']
    if change == 'missing-issuer': del claims['iss']
    if change == 'wrong-issuer': claims['iss'] = 'other'
    if change == 'expired': claims['exp'] = datetime.now(timezone.utc)-timedelta(minutes=1)
    token = jwt.encode(claims, SECRET, algorithm='HS256')
    with pytest.raises(HTTPException): auth.require_auth(None, token)
    assert verify_session_token(token) is None


def test_valid_local_token(monkeypatch):
    monkeypatch.setattr(auth, 'ENABLE_LOCAL_AUTH', True, raising=False)
    monkeypatch.setattr(auth, 'LOCAL_AUTH_SECRET_KEY', SECRET)
    claims = dict(iss='local', username='synthetic-user', exp=datetime.now(timezone.utc)+timedelta(minutes=5))
    token = jwt.encode(claims, SECRET, algorithm='HS256')
    assert auth.require_auth(None, token)['auth_type'] == 'local'
    assert verify_session_token(token)['auth_type'] == 'local'


def test_valid_v1_entra_token(entra, monkeypatch):
    private, claims, key = entra
    claims['ver'] = '1.0'
    claims['iss'] = f'https://sts.windows.net/{TENANT}/'
    key._jwk_data['issuer'] = 'https://sts.windows.net/{tenantid}/'
    monkeypatch.setattr(auth, 'jwks_client_v1', auth.jwks_client)
    assert auth.require_auth(None, jwt.encode(claims, private, algorithm='RS256'))['sub'] == 'synthetic-user'


def test_string_false_does_not_grant_admin(monkeypatch):
    monkeypatch.setattr(auth, 'is_testing', False)
    monkeypatch.setattr(auth, 'allowed_admin_users', [])
    with pytest.raises(HTTPException) as error:
        auth.require_admin({'auth_type':'local', 'is_admin':'False', 'email':'user@example.test'})
    assert error.value.status_code == 403
