"""Entry point for Respondr backend (refactored)."""
from app import app  # type: ignore  # FastAPI instance
from app.llm import extract_details_from_text, client
from app.storage import load_messages, save_messages
from typing import Any, Dict, List

# In-memory message store
messages: List[Dict[str, Any]] = []
load_messages()

# Variables used by internal ACR webhook tests
ACR_WEBHOOK_TOKEN = None
K8S_NAMESPACE = "default"
K8S_DEPLOYMENT = "respondr"

__all__ = [
    "app",
    "extract_details_from_text",
    "client",
    "messages",
    "load_messages",
    "save_messages",
    "ACR_WEBHOOK_TOKEN",
    "K8S_NAMESPACE",
    "K8S_DEPLOYMENT",
]
