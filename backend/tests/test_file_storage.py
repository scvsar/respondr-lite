"""File storage must preserve records when reads or writes fail."""
import json
from unittest.mock import patch

import pytest

from app.storage_backends import FileStorage


@pytest.mark.parametrize('contents', ['{invalid', '{}', '[1]', 'null'])
def test_invalid_file_cannot_be_overwritten_by_add(tmp_path, contents):
    active = tmp_path / 'active.json'
    active.write_text(contents, encoding='utf-8')
    store = FileStorage(str(active), str(tmp_path / 'deleted.json'))
    with pytest.raises((ValueError, RuntimeError)):
        store.add_message({'id': 'new'})
    assert active.read_text(encoding='utf-8') == contents
    assert store.is_healthy() is False


def test_failed_serialization_preserves_existing_file(tmp_path):
    active = tmp_path / 'active.json'
    contents = '[{"id":"original"}]'
    active.write_text(contents, encoding='utf-8')
    store = FileStorage(str(active), str(tmp_path / 'deleted.json'))
    assert store.save_messages([{'id': 'new', 'bad': object()}]) is False
    assert active.read_text(encoding='utf-8') == contents
    assert list(tmp_path.iterdir()) == [active]


def test_failed_replace_preserves_existing_file(tmp_path):
    active = tmp_path / 'active.json'
    contents = '[{"id":"original"}]'
    active.write_text(contents, encoding='utf-8')
    store = FileStorage(str(active), str(tmp_path / 'deleted.json'))
    with patch('os.replace', side_effect=OSError('synthetic failure')):
        assert store.save_messages([{'id': 'new'}]) is False
    assert active.read_text(encoding='utf-8') == contents
    assert list(tmp_path.iterdir()) == [active]


def test_missing_file_and_round_trip(tmp_path):
    active, deleted = tmp_path / 'active.json', tmp_path / 'deleted.json'
    store = FileStorage(str(active), str(deleted))
    assert store.get_messages() == []
    assert store.is_healthy() is True
    assert store.add_message({'id': 'one', 'text': 'Synthetic response'}) is True
    assert store.add_message({'id': 'one', 'text': 'Synthetic correction'}) is True
    assert store.get_messages() == [{'id': 'one', 'text': 'Synthetic correction'}]
    assert json.loads(active.read_text()) == store.get_messages()
    assert store.save_deleted_messages([{'id': 'deleted'}]) is True
    assert store.get_deleted_messages() == [{'id': 'deleted'}]
