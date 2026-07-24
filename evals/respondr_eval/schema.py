"""Versioned data contracts for extraction evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
VALID_STATUSES = (
    "Responding",
    "Available",
    "Informational",
    "Cancelled",
    "Not Responding",
    "Unknown",
)
REVIEWED_STATES = {"approved", "corrected"}
ANNOTATION_STATES = REVIEWED_STATES | {"proposed", "skipped"}
VALID_SPLITS = {"train", "dev", "test", "unassigned"}


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def normalize_status(value: Any) -> str:
    text = str(value or "Unknown").strip()
    aliases = {
        "arrived": "Responding",
        "on route": "Responding",
        "eta format unknown": "Unknown",
        "eta parse error": "Unknown",
        "not responding": "Not Responding",
        "cancelled": "Cancelled",
        "canceled": "Cancelled",
    }
    normalized = aliases.get(text.lower(), text)
    if normalized not in VALID_STATUSES:
        raise ValueError(f"Unsupported status: {value!r}")
    return normalized


def normalize_vehicle(value: Any) -> str:
    text = str(value or "Unknown").strip()
    if not text or text.lower() == "unknown":
        return "Unknown"
    if text.upper() == "POV":
        return "POV"
    if text.lower() in {"sar rig", "sar-rig"}:
        return "SAR Rig"
    match = re.fullmatch(r"sar[\s-]?0*(\d{1,3})", text, flags=re.IGNORECASE)
    if match:
        unit = int(match.group(1))
        if 1 <= unit <= 199:
            return f"SAR-{unit}"
    raise ValueError(f"Unsupported vehicle: {value!r}")


def normalize_eta_iso(value: Any) -> str:
    text = str(value or "Unknown").strip()
    if not text or text.lower() in {"unknown", "none", "null"}:
        return "Unknown"
    parsed = _parse_datetime(text, "eta_iso").astimezone(timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ReferenceLabel:
    status: str
    vehicle: str
    eta_iso: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReferenceLabel":
        return cls(
            status=normalize_status(value.get("status")),
            vehicle=normalize_vehicle(value.get("vehicle")),
            eta_iso=normalize_eta_iso(value.get("eta_iso")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "vehicle": self.vehicle,
            "eta_iso": self.eta_iso,
        }


@dataclass
class EvalCase:
    case_id: str
    input: dict[str, Any]
    reference: ReferenceLabel
    split: str = "unassigned"
    annotation: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    observations: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvalCase":
        version = str(value.get("schema_version") or "")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version {version!r}; expected {SCHEMA_VERSION!r}"
            )

        case_id = str(value.get("case_id") or "").strip()
        if not case_id:
            raise ValueError("case_id is required")

        input_value = dict(value.get("input") or {})
        text = input_value.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{case_id}: input.text is required")
        base_time = str(input_value.get("base_time") or "")
        _parse_datetime(base_time, f"{case_id}: input.base_time")
        previous = input_value.get("previous_messages", [])
        if not isinstance(previous, list):
            raise ValueError(f"{case_id}: input.previous_messages must be a list")

        split = str(value.get("split") or "unassigned")
        if split not in VALID_SPLITS:
            raise ValueError(f"{case_id}: unsupported split {split!r}")

        annotation = dict(value.get("annotation") or {})
        state = str(annotation.get("state") or "proposed")
        if state not in ANNOTATION_STATES:
            raise ValueError(f"{case_id}: unsupported annotation state {state!r}")
        annotation["state"] = state

        return cls(
            case_id=case_id,
            input=input_value,
            reference=ReferenceLabel.from_dict(value.get("reference") or {}),
            split=split,
            annotation=annotation,
            provenance=dict(value.get("provenance") or {}),
            observations=dict(value.get("observations") or {}),
            schema_version=version,
        )

    @property
    def is_reviewed(self) -> bool:
        return self.annotation.get("state") in REVIEWED_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "split": self.split,
            "input": self.input,
            "reference": self.reference.to_dict(),
            "annotation": self.annotation,
            "provenance": self.provenance,
            "observations": self.observations,
        }
