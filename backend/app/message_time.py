"""Shared timestamp policy for responder date windows."""
from datetime import datetime, timezone
from typing import Any

from .utils import parse_datetime_like


def parse_cutoff(value: str | None) -> datetime | None:
    if value is None:
        return None
    cutoff = parse_datetime_like(value)
    if cutoff is None:
        raise ValueError('Invalid time cutoff')
    return cutoff.astimezone(timezone.utc)


def messages_since(messages: list[dict[str, Any]], cutoff: datetime | None) -> list[dict[str, Any]]:
    if cutoff is None:
        return messages
    result = []
    for message in messages:
        stamp = parse_datetime_like(message.get('timestamp_utc') or message.get('timestamp'))
        # A missing timestamp cannot prove that a record belongs in this window.
        if stamp is not None and stamp.astimezone(timezone.utc) >= cutoff:
            result.append(message)
    return result
