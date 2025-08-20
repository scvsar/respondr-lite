import json
import os
import uuid
from typing import Any, Dict, List

from .config import logger, is_testing

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "respondr_messages.json")

def ensure_message_ids(messages: List[Dict[str, Any]]) -> None:
    for m in messages:
        if "id" not in m:
            m["id"] = str(uuid.uuid4())

def load_messages() -> None:
    import main  # type: ignore

    if is_testing and not os.path.exists(DATA_FILE):
        main.messages = []
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            main.messages = json.load(f)
    except Exception:
        main.messages = []
    ensure_message_ids(main.messages)

def save_messages() -> None:
    import main  # type: ignore

    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(main.messages, f)
    except Exception as e:
        logger.error(f"Failed to save messages: {e}")
