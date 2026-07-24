"""Deterministic, no-network extraction baseline."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..schema import EvalCase
from .base import Prediction, Strategy


NEGATIVE_PHRASES = (
    "not responding",
    "can't make it",
    "cannot make it",
    "won't make it",
    "standing down",
    "stand down",
    "10-22",
    "1022",
    "turning around",
    "subject found",
)
CANCEL_PHRASES = ("cancelled", "canceled", "cancelling", "canceling")
AVAILABLE_PHRASES = ("available", "can respond if needed", "on standby", "standing by")
RESPONSE_PHRASES = (
    "responding",
    "en route",
    "enroute",
    "on my way",
    "omw",
    "rolling",
    "headed",
    "leaving now",
    "be there",
    "arriving",
    "eta",
)


def _status(text: str) -> tuple[str, float, str]:
    lowered = f" {text.lower()} "
    if any(phrase in lowered for phrase in CANCEL_PHRASES):
        return "Cancelled", 0.98, "explicit cancellation"
    if any(phrase in lowered for phrase in NEGATIVE_PHRASES):
        return "Not Responding", 0.98, "explicit negative response"
    if any(phrase in lowered for phrase in AVAILABLE_PHRASES):
        return "Available", 0.9, "explicit availability"
    if any(phrase in lowered for phrase in RESPONSE_PHRASES):
        return "Responding", 0.92, "response phrase"
    if re.search(r"\bsar[\s-]?0*\d{1,3}\b", lowered) and re.search(
        r"\b(taking|driving|in|with|grab|using)\b", lowered
    ):
        return "Responding", 0.82, "vehicle response pattern"
    if "?" in text or re.search(
        r"\b(ic|icp|operations|planning|logistics|assignment|staging)\b", lowered
    ):
        return "Informational", 0.72, "informational pattern"
    return "Unknown", 0.35, "insufficient evidence"


def _vehicle(text: str, status: str) -> tuple[str, str]:
    lowered = text.lower()
    if re.search(r"\bsar[\s-]?rig\b|\bthe rig\b", lowered):
        return "SAR Rig", "explicit SAR rig"
    match = re.search(r"\bsar[\s-]?0*(\d{1,3})\b", lowered)
    if not match:
        match = re.search(
            r"\b(?:taking|driving|in|grab(?:bing)?|using)\s+(?:the\s+)?0*(\d{1,3})\b",
            lowered,
        )
    if match:
        unit = int(match.group(1))
        if 1 <= unit <= 199:
            return f"SAR-{unit}", "explicit SAR unit"
    if re.search(r"\b(pov|personal vehicle|driving myself|my car|own car)\b", lowered):
        return "POV", "explicit personal vehicle"
    if status == "Responding":
        return "POV", "responding default"
    return "Unknown", "no vehicle evidence"


def _base_time(case: EvalCase) -> datetime:
    parsed = datetime.fromisoformat(
        str(case.input["base_time"]).replace("Z", "+00:00")
    )
    timezone_name = case.input.get("timezone")
    if timezone_name:
        parsed = parsed.astimezone(ZoneInfo(str(timezone_name)))
    return parsed


def _eta(text: str, base: datetime, status: str, previous_eta: str | None) -> tuple[str, str]:
    if status in {"Not Responding", "Cancelled"}:
        return "Unknown", "status clears ETA"
    lowered = text.lower()
    if previous_eta and re.search(r"\b(same eta|eta unchanged|keep.*eta)\b", lowered):
        return previous_eta, "explicit previous ETA"

    range_match = re.search(
        r"\b(\d{1,3})\s*[-~]\s*(\d{1,3})\s*(?:min|mins|minute|minutes)\b",
        lowered,
    )
    if range_match:
        minutes = max(int(range_match.group(1)), int(range_match.group(2)))
        return _to_utc(base + timedelta(minutes=minutes)), "duration range"

    duration_match = re.search(
        r"\b(\d{1,3})\s*(?:min|mins|minute|minutes|m)\b", lowered
    )
    if duration_match:
        return _to_utc(base + timedelta(minutes=int(duration_match.group(1)))), "duration"

    hours_match = re.search(
        r"\b(\d{1,2})(?:\s*(?:hr|hrs|hour|hours))"
        r"(?:\s*(?:and)?\s*(\d{1,2})\s*(?:min|mins|minute|minutes))?\b",
        lowered,
    )
    if hours_match:
        minutes = int(hours_match.group(1)) * 60 + int(hours_match.group(2) or 0)
        return _to_utc(base + timedelta(minutes=minutes)), "duration"

    ampm_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
    if ampm_match:
        hour = int(ampm_match.group(1))
        minute = int(ampm_match.group(2) or 0)
        if 1 <= hour <= 12 and minute <= 59:
            if ampm_match.group(3) == "pm" and hour != 12:
                hour += 12
            elif ampm_match.group(3) == "am" and hour == 12:
                hour = 0
            return _clock_eta(base, hour, minute), "local clock time"

    colon_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", lowered)
    if colon_match and not re.search(
        r"\b(left|last seen|departed|reported|call received)\b", lowered
    ):
        return _clock_eta(base, int(colon_match.group(1)), int(colon_match.group(2))), "local clock time"

    military_match = re.search(r"\b((?:[01]\d|2[0-3])[0-5]\d)\b", lowered)
    if military_match and military_match.group(1) != "1022":
        value = military_match.group(1)
        return _clock_eta(base, int(value[:2]), int(value[2:])), "military time"

    return "Unknown", "no ETA evidence"


def _clock_eta(base: datetime, hour: int, minute: int) -> str:
    eta = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if eta <= base:
        eta += timedelta(days=1)
    return _to_utc(eta)


def _to_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class HeuristicStrategy(Strategy):
    kind = "heuristic"

    def __init__(self, name: str = "heuristic-v1"):
        self.name = name

    def predict(self, case: EvalCase) -> Prediction:
        started = time.perf_counter()
        text = str(case.input["text"])
        status, confidence, status_reason = _status(text)
        vehicle, vehicle_reason = _vehicle(text, status)
        previous_eta = case.input.get("previous_eta_iso")
        eta_iso, eta_reason = _eta(text, _base_time(case), status, previous_eta)
        return Prediction(
            status=status,
            vehicle=vehicle,
            eta_iso=eta_iso,
            confidence=confidence,
            latency_ms=(time.perf_counter() - started) * 1000,
            metadata={
                "status_reason": status_reason,
                "vehicle_reason": vehicle_reason,
                "eta_reason": eta_reason,
            },
        ).validated()
