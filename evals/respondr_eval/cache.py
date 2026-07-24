"""Append-only prediction cache for repeatable paid experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

from .strategies.base import Prediction


class PredictionCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._items: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        item = json.loads(line)
                        self._items[item["key"]] = item["prediction"]

    @staticmethod
    def key(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get(self, key: str) -> Prediction | None:
        value = self._items.get(key)
        return Prediction.from_dict(value) if value else None

    def put(self, key: str, prediction: Prediction) -> None:
        record = {"key": key, "prediction": prediction.to_dict()}
        with self._lock:
            if key in self._items:
                return
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
            self._items[key] = record["prediction"]
