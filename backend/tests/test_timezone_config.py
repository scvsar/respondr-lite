"""Configured timezones must preserve regional daylight saving rules."""
from datetime import datetime, timedelta

import pytest

from app.config import get_timezone


@pytest.mark.parametrize('name,winter,summer', [
    ('UTC', 0, 0),
    ('America/Los_Angeles', -8, -7),
    ('America/New_York', -5, -4),
    ('Asia/Kolkata', 5.5, 5.5),
])
def test_configured_zone_offsets(name, winter, summer):
    zone = get_timezone(name)
    assert datetime(2026, 1, 15, tzinfo=zone).utcoffset() == timedelta(hours=winter)
    assert datetime(2026, 7, 15, tzinfo=zone).utcoffset() == timedelta(hours=summer)


def test_invalid_zone_fails_instead_of_using_pacific_time():
    with pytest.raises(ValueError):
        get_timezone('Invalid/Zone')
