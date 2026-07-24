"""Common strategy interface and prediction contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from ..schema import EvalCase, normalize_eta_iso, normalize_status, normalize_vehicle


@dataclass
class Prediction:
    status: str = "Unknown"
    vehicle: str = "Unknown"
    eta_iso: str = "Unknown"
    confidence: float | None = None
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    retry_count: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validated(self) -> "Prediction":
        if self.error:
            return self
        try:
            self.status = normalize_status(self.status)
            self.vehicle = normalize_vehicle(self.vehicle)
            self.eta_iso = normalize_eta_iso(self.eta_iso)
        except ValueError as exc:
            self.error = f"invalid_prediction: {exc}"
            self.status = "Unknown"
            self.vehicle = "Unknown"
            self.eta_iso = "Unknown"
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Prediction":
        return cls(**value).validated()


class Strategy(ABC):
    name: str
    kind: str

    def fit(
        self, train_cases: list[EvalCase], dev_cases: list[EvalCase] | None = None
    ) -> None:
        del train_cases, dev_cases

    @abstractmethod
    def predict(self, case: EvalCase) -> Prediction:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind}
