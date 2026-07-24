"""Versioned model pricing and experiment cost calculations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelPrice:
    input_usd_per_million: float
    output_usd_per_million: float


class PricingCatalog:
    def __init__(self, effective_date: str, models: dict[str, ModelPrice]):
        self.effective_date = effective_date
        self.models = models

    @classmethod
    def load(cls, path: str | Path) -> "PricingCatalog":
        value: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        effective_date = str(value.get("effective_date") or "").strip()
        if not effective_date:
            raise ValueError("Pricing catalog requires effective_date")
        models = {}
        for model, entry in (value.get("models") or {}).items():
            input_price = entry.get("input_usd_per_million")
            output_price = entry.get("output_usd_per_million")
            if input_price is None or output_price is None:
                continue
            models[str(model)] = ModelPrice(float(input_price), float(output_price))
        return cls(effective_date, models)

    def calculate(self, model_id: str, input_tokens: int, output_tokens: int) -> float | None:
        price = self.models.get(model_id)
        if not price:
            return None
        return (
            input_tokens * price.input_usd_per_million
            + output_tokens * price.output_usd_per_million
        ) / 1_000_000
