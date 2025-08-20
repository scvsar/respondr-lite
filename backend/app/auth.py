from typing import Optional
from fastapi import Header, HTTPException

from .config import (
    webhook_api_key,
    disable_api_key_check,
)

def validate_webhook_api_key(x_api_key: Optional[str] = Header(None)) -> bool:
    if disable_api_key_check:
        return True
    if webhook_api_key and x_api_key == webhook_api_key:
        return True
    raise HTTPException(status_code=401, detail="Invalid API key")
