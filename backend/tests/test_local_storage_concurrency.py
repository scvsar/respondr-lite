"""Local backends must preserve independent writes and return isolated records."""
from concurrent.futures import ThreadPoolExecutor

from app.storage_backends import FileStorage, MemoryStorage


def test_file_backend_preserves_concurrent_additions(tmp_path):
    store = FileStorage(str(tmp_path / 'active.json'), str(tmp_path / 'deleted.json'))
    rows = [{'id': str(index), 'text': 'Synthetic message'} for index in range(40)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(store.add_message, rows))
    assert {row['id'] for row in store.get_messages()} == {row['id'] for row in rows}


def test_memory_reads_and_writes_do_not_share_mutable_records():
    store = MemoryStorage()
    row = {'id':'synthetic','attachments':[{'type':'image','url':'https://example.test/image'}]}
    store.add_message(row)
    row['attachments'][0]['url'] = 'changed by caller'
    read = store.get_messages()
    assert read[0]['attachments'][0]['url'] == 'https://example.test/image'
    read[0]['attachments'].clear()
    assert store.get_messages()[0]['attachments']
