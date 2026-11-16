"""Both responder views must enforce the same date window."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.responders import get_responders, get_current_status


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', [get_responders, get_current_status])
@pytest.mark.parametrize('since', ['not-a-date', '', '2026-13-01'])
async def test_invalid_cutoff_is_rejected(endpoint, since):
    with patch('app.routers.responders.get_messages', return_value=[]) as read:
        with pytest.raises(HTTPException) as caught:
            await endpoint(since, {})
    assert caught.value.status_code == 400
    read.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', [get_responders, get_current_status])
async def test_cutoff_uses_utc_and_includes_boundary(endpoint):
    rows = [
        {'id': 'old', 'name': 'Old synthetic user', 'timestamp': '2026-02-22T18:50:56Z'},
        {'id': 'boundary', 'name': 'Boundary synthetic user', 'timestamp': '2026-11-13T04:00:00-08:00'},
        {'id': 'recent', 'name': 'Recent synthetic user', 'timestamp_utc': '2026-11-14T00:00:00Z', 'timestamp': 'invalid'},
        {'id': 'invalid', 'name': 'Invalid synthetic user', 'timestamp': 'invalid'},
        {'id': 'missing', 'name': 'Missing synthetic user'},
    ]
    with patch('app.routers.responders.get_messages', return_value=rows):
        result = await endpoint('2026-11-13T12:00:00Z', {})
        all_result = await endpoint(None, {})
    assert {row['id'] for row in result} == {'boundary', 'recent'}
    assert len(all_result) == 5
