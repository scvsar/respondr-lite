from unittest.mock import MagicMock, patch
from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError
from app.storage_backends import AzureTableStorage
from app import storage
from types import SimpleNamespace


class Entity(dict):
    metadata = {'etag': 'synthetic-etag'}


def backend():
    obj = AzureTableStorage.__new__(AzureTableStorage)
    obj.table_name = 'SyntheticMessages'
    obj._client = MagicMock()
    table = obj._client.get_table_client.return_value
    table.get_entity.return_value = Entity(PartitionKey='messages', RowKey='source-1', text='Synthetic message')
    return obj, table


def test_default_table_name_matches_infrastructure(monkeypatch):
    monkeypatch.delenv('STORAGE_TABLE_NAME', raising=False)
    with patch.object(AzureTableStorage, '_init_client'):
        obj = AzureTableStorage('synthetic-configuration')
    assert obj.table_name == 'ResponderMessages'


def test_edit_only_updates_one_row_with_concurrency_check():
    obj, table = backend()
    with patch.object(obj, 'is_healthy', return_value=True):
        assert obj.update_message('source-1', {'vehicle': 'Unknown'})
    table.update_entity.assert_called_once()
    assert table.update_entity.call_args.kwargs['etag'] == 'synthetic-etag'
    assert table.update_entity.call_args.kwargs['match_condition'] == MatchConditions.IfNotModified
    table.query_entities.assert_not_called()
    table.delete_entity.assert_not_called()


def test_delete_copies_before_removing_source():
    obj, table = backend()
    with patch.object(obj, 'is_healthy', return_value=True):
        assert obj.move_message('source-1', 'messages', 'deleted')
    names = [call[0] for call in table.method_calls]
    assert names.index('upsert_entity') < names.index('delete_entity')
    assert table.upsert_entity.call_args.args[0]['PartitionKey'] == 'deleted'
    assert table.delete_entity.call_args.kwargs['etag'] == 'synthetic-etag'


def test_failed_archive_never_deletes_source():
    obj, table = backend()
    table.upsert_entity.side_effect = RuntimeError('synthetic outage')
    with patch.object(obj, 'is_healthy', return_value=True):
        assert obj.move_message('source-1', 'messages', 'deleted') is False
    table.delete_entity.assert_not_called()


def test_concurrent_edit_during_delete_is_not_reported_as_success():
    obj, table = backend()
    table.delete_entity.side_effect = ResourceModifiedError('synthetic conflict')
    with patch.object(obj, 'is_healthy', return_value=True):
        assert obj.move_message('source-1', 'messages', 'deleted') is False


def test_runtime_edit_uses_row_operation(monkeypatch):
    obj, table = backend()
    monkeypatch.setattr(storage, 'is_testing', False)
    monkeypatch.setattr(storage, '_storage_manager', SimpleNamespace(
        current_backend=obj, _ensure_backend=lambda: None))
    with patch.object(obj, 'is_healthy', return_value=True):
        assert storage.update_message('source-1', {'vehicle':'SAR-7'})
    table.query_entities.assert_not_called()
    table.delete_entity.assert_not_called()


def test_retention_does_not_remove_a_record_changed_since_selection():
    obj, table = backend()
    table.get_entity.return_value['created_at'] = '200'
    with patch.object(obj, 'is_healthy', return_value=True):
        assert obj.remove_message('source-1', 'messages', {'created_at':100}) is False
    table.delete_entity.assert_not_called()


def test_restore_removes_deletion_marker_and_preserves_source_fields():
    obj, table = backend()
    table.get_entity.return_value['PartitionKey'] = 'deleted'
    table.get_entity.return_value['deleted_at'] = '2026-01-01T00:00:00Z'
    with patch.object(obj, 'is_healthy', return_value=True):
        assert obj.move_message('source-1', 'deleted', 'messages')
    target = table.upsert_entity.call_args.args[0]
    assert target['PartitionKey'] == 'messages'
    assert target['text'] == 'Synthetic message'
    assert 'deleted_at' not in target


def test_boolean_source_flags_survive_storage_round_trip():
    obj,_=backend()
    entity=obj._message_to_entity({'id':'source-1','system':True,'extraction_failed':False})
    result=obj._entity_to_message(entity)
    assert result['system'] is True
    assert result['extraction_failed'] is False
