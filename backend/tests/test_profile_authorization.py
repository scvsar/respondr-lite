"""The profile must show the same admin policy that the API enforces."""
import json

from fastapi import HTTPException
import pytest

from app.auth import dependencies as auth
from app.routers.user import get_user_info


@pytest.mark.parametrize('user,allowed,expected', [
    ({'auth_type': 'entra', 'email': 'user@example.test', 'is_admin': True}, [], False),
    ({'auth_type': 'local', 'email': 'user@example.test', 'is_admin': 'False'}, [], False),
    ({'auth_type': 'local', 'email': 'user@example.test', 'is_admin': True}, [], True),
    ({'auth_type': 'local', 'email': 'user@example.test', 'is_admin': False}, [], False),
    ({'auth_type': 'entra', 'preferred_username': 'Admin@Example.Test'}, ['admin@example.test'], True),
    ({'auth_type': 'local', 'email': 'Admin@Example.Test', 'is_admin': False}, ['admin@example.test'], True),
    ({'auth_type': 'entra', 'emails': ['admin@example.test']}, ['admin@example.test'], True),
    ({'auth_type': 'entra', 'is_admin': True}, [], False),
])
def test_profile_and_api_admin_policy_match(monkeypatch, user, allowed, expected):
    monkeypatch.setattr(auth, 'is_testing', False)
    monkeypatch.setattr(auth, 'allowed_admin_users', allowed)
    profile = json.loads(get_user_info(user).body)
    assert profile['is_admin'] is expected
    if expected:
        assert auth.require_admin(user) == user
    else:
        with pytest.raises(HTTPException) as caught:
            auth.require_admin(user)
        assert caught.value.status_code == 403
