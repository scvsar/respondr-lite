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
    sender_id: Optional[str] = None
    sender_type: Optional[str] = None
    source_guid: Optional[str] = None
    system: bool = False
    text: Optional[str] = None
    user_id: Optional[str] = None

    @field_validator("created_at")
    def validate_created_at(cls, v: int) -> int:  # type: ignore[override]
        if v < 0:
            raise ValueError("created_at must be a positive integer timestamp")
        return v
