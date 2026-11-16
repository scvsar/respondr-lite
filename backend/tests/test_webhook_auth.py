from unittest.mock import patch

from fastapi.testclient import TestClient
from app import app


def test_http_webhook_rejects_missing_key_before_processing(monkeypatch):
    monkeypatch.setattr('app.routers.webhook.webhook_api_key', 'synthetic-key')
    monkeypatch.setattr('app.routers.webhook.disable_api_key_check', False)
    with patch('app.routers.webhook.add_message') as save, patch('app.routers.webhook.extract_details_from_text') as extract:
        response = TestClient(app).post('/webhook', json={
            'name': 'Synthetic User', 'text': 'Responding', 'created_at': 1794797000,
        })
    assert response.status_code == 401
    save.assert_not_called()
    extract.assert_not_called()
