"""Validate structured extraction fields before responder data can use them."""

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelExtraction(BaseModel):
    model_config = ConfigDict(extra='ignore')
    vehicle: str = Field(pattern=r'^(?:POV|SAR Rig|Unknown|SAR-\d+)$')
    status: Literal['Responding','Cancelled','Not Responding','Informational','Available','Unknown']
    eta_iso: str
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    evidence: str = ''

    @field_validator('eta_iso')
    @classmethod
    def validate_eta(cls, value):
        if value == 'Unknown':
            return value
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('ETA must include a timezone')
        return parsed.astimezone(timezone.utc).isoformat()
