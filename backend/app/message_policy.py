"""Identify GroupMe system notices without classifying ordinary chat text."""

import re
from typing import Any, Mapping


def is_system_notice(message: Mapping[str, Any]) -> bool:
    flag = message.get("system")
    if flag is True or str(flag).lower() == "true":
        return True
    if str(message.get("sender_type") or "").lower() == "system":
        return True
    if message.get("message_kind") == "system":
        return True
    # Older records discarded source flags. Require the service sender as well as notice text.
    if str(message.get("name") or "").strip().lower() != "groupme":
        return False
    text = str(message.get("text") or "").strip()
    return bool(re.fullmatch(
        r"(?:A message was deleted\.|.+ (?:added|removed) .+ (?:to|from) the group\.|"
        r".+ (?:joined|left) the group\.)",
        text,
        re.IGNORECASE,
    ))


def responder_messages(messages):
    """Exclude system notices from responder data and extraction history."""
    return [message for message in messages if not is_system_notice(message)]
