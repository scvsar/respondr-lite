from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


class GroupMeAttachment(BaseModel):
    # attachments are opaque in the example; allow any list of dicts
    type: Optional[str] = None
    url: Optional[str] = None


class GroupMeMessage(BaseModel):
    attachments: List[Any] = Field(default_factory=list)
    avatar_url: Optional[str] = None
    created_at: int
    group_id: str
    id: str
    name: str
    sender_id: str  # Required - identifies the sender
    sender_type: str  # Required - typically "user" or "bot"
    source_guid: str  # Required - unique identifier for the message
    system: bool = False
    text: str  # Required - the message content
    user_id: str  # Required - user who sent the message

    @field_validator("created_at")
    def validate_created_at(cls, v: int) -> int:  # type: ignore[override]
        if v < 0:
            raise ValueError("created_at must be a positive integer timestamp")
        return v
