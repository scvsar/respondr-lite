from unittest.mock import MagicMock
import pytest
from app import storage
from app.storage_backends import MemoryStorage, StorageBackend


def manager(monkeypatch, healthy=False, fallback=False):
    monkeypatch.setattr(storage, 'is_testing', False)
    obj = storage.StorageManager.__new__(storage.StorageManager)
    obj.allow_fallback = fallback
    obj.primary_backend = MagicMock()
    obj.primary_backend.backend_type = StorageBackend.AZURE_TABLE
    obj.primary_backend.is_healthy.return_value = healthy
    obj.fallback_backend = MemoryStorage()
    obj.current_backend = obj.primary_backend
    return obj


def test_unhealthy_azure_does_not_acknowledge_memory_write(monkeypatch):
    obj = manager(monkeypatch)
    with pytest.raises(RuntimeError): obj.add_message({'id':'synthetic-1'})
    assert obj.fallback_backend.get_messages() == []


def test_azure_write_failure_is_not_retried_in_memory(monkeypatch):
    obj = manager(monkeypatch, healthy=True)
    obj.primary_backend.add_message.return_value = False
    assert obj.add_message({'id':'synthetic-1'}) is False
    assert obj.fallback_backend.get_messages() == []


def test_azure_read_failure_is_not_reported_as_empty(monkeypatch):
    obj = manager(monkeypatch, healthy=True)
    obj.primary_backend.get_messages.side_effect = RuntimeError('synthetic outage')
    with pytest.raises(RuntimeError): obj.get_messages()


def test_explicit_fallback_remains_available(monkeypatch):
    obj = manager(monkeypatch, fallback=True)
    assert obj.add_message({'id':'synthetic-1'}) is True
    assert obj.fallback_backend.get_messages() == [{'id':'synthetic-1'}]
