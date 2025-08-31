"""Entry point for Respondr backend (refactored)."""
from app import app  
from app.llm import extract_details_from_text, client
from typing import Any, Dict, List

# In-memory message store for test compatibility when not running live
messages: List[Dict[str, Any]] = []


__all__ = [
    "app",
    "extract_details_from_text", 
    "client",
    "messages",
]
