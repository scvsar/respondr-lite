"""Resolve responder identity while retaining compatibility with older records."""

import json
import math


def source_user_id(message):
    return str(message.get('user_id') or message.get('sender_id') or '')


def attach_responder_keys(messages):
    known = {}
    for message in messages:
        name = str(message.get('name') or '').strip().casefold()
        group = str(message.get('group_id') or 'unknown')
        user = source_user_id(message)
        if name and user:
            known.setdefault((group, name), set()).add(user)
    result = []
    for message in messages:
        name = str(message.get('name') or '').strip().casefold()
        group = str(message.get('group_id') or 'unknown')
        user = source_user_id(message)
        candidates = known.get((group, name), set())
        # Join legacy names only when the known identity is unambiguous in this group.
        if not user and len(candidates) == 1:
            user = next(iter(candidates))
        identity = ('user', user) if user else ('name', name) if name else ('message', str(message.get('id') or ''))
        result.append({**message, 'responder_key': json.dumps([group, *identity], separators=(',', ':'))})
    return result


def message_epoch(message):
    try:
        value = float(message.get('created_at', 0))
        return value if math.isfinite(value) else 0
    except (TypeError, ValueError):
        return 0
