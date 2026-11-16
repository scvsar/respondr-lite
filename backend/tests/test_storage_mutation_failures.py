"""Storage failures must not report successful edits or lose source records."""
from unittest.mock import Mock

import pytest

from app import storage


@pytest.fixture
def collections(monkeypatch):
    active = [{'id': 'one', 'text': 'Synthetic original'}]
    deleted = []
    monkeypatch.setattr(storage, '_azure_row_backend', lambda: None)
    monkeypatch.setattr(storage, 'get_messages', lambda: [dict(row) for row in active])
    monkeypatch.setattr(storage, 'get_deleted_messages', lambda: [dict(row) for row in deleted])
    save_active = Mock(return_value=True)
    save_deleted = Mock(return_value=False)
    monkeypatch.setattr(storage, 'save_messages', save_active)
    monkeypatch.setattr(storage, 'save_deleted_messages', save_deleted)
    return active, deleted, save_active, save_deleted


def test_failed_delete_destination_keeps_source(collections):
    _, _, save_active, save_deleted = collections
    assert storage.delete_message('one') is False
    save_active.assert_not_called()
    save_deleted.assert_called_once()


def test_failed_update_returns_false(collections):
    _, _, save_active, _ = collections
    save_active.return_value = False
    assert storage.update_message('one', {'text': 'Synthetic correction'}) is False


def test_failed_restore_destination_keeps_deleted_source(collections):
    active, deleted, save_active, save_deleted = collections
    deleted.extend(active)
    active.clear()
    save_active.return_value = False
    assert storage.undelete_message('one') is False
    save_deleted.assert_not_called()


def test_failed_purge_returns_false(collections):
    active, deleted, _, _ = collections
    deleted.extend(active)
    active.clear()
    assert storage.permanently_delete_message('one') is False
    assert storage.clear_all_deleted_messages() == 0


@pytest.mark.parametrize('operation', [lambda: storage.clear_all_messages(), lambda: storage.bulk_delete_messages(['one'])])
def test_failed_bulk_destination_does_not_clear_source(collections, operation):
    _, _, save_active, _ = collections
    assert operation() == 0
    save_active.assert_not_called()
