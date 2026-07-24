from datetime import datetime, timezone
from unittest.mock import patch

from app.config import APP_TZ
from app.llm import extract_details_from_text


def test_evaluation_can_inject_client_without_changing_default_output():
    injected_client = object()
    response = {
        "status": "Responding",
        "vehicle": "POV",
        "eta_iso": "2026-07-24T01:00:00Z",
        "confidence": 0.95,
        "evidence": "responding",
    }

    with patch("app.llm._call_llm_only", return_value=response) as call:
        result = extract_details_from_text(
            "Responding POV ETA 1800",
            base_time=datetime(2026, 7, 24, tzinfo=timezone.utc),
            llm_client=injected_client,
        )

    assert call.call_args.args[3] is injected_client
    assert result["raw_status"] == "Responding"
    assert result["vehicle"] == "POV"


def test_rules_apply_only_to_current_message_when_history_contains_decline():
    current = "Responding POV to staging. ETA 1000."
    enriched = (
        "Previous messages from this user:\n"
        '- [earlier] "Synthetic decline" -> Status: Not Responding, '
        "Vehicle: Unknown, ETA: Unknown\n\n"
        f"Current message: {current}"
    )
    response = {
        "status": "Responding",
        "vehicle": "POV",
        "eta_iso": "Unknown",
        "confidence": 0.95,
        "evidence": "current response",
    }
    base_time = datetime(2026, 5, 19, 7, 55, tzinfo=APP_TZ)

    with patch("app.llm._call_llm_only", return_value=response):
        result = extract_details_from_text(
            enriched,
            base_time=base_time,
            rule_text=current,
        )

    assert result["raw_status"] == "Responding"
    assert result["vehicle"] == "POV"
    assert result["eta_timestamp_utc"] == "2026-05-19T17:00:00+00:00"
    assert result["rules_applied"] == []
    assert result["model_status"] == "Responding"


def test_historical_replay_uses_message_time_for_eta_minutes():
    response = {
        "status": "Responding",
        "vehicle": "POV",
        "eta_iso": "Unknown",
        "confidence": 0.95,
        "evidence": "current response",
    }
    base_time = datetime(2026, 5, 19, 7, 55, tzinfo=APP_TZ)

    with patch("app.llm._call_llm_only", return_value=response) as call:
        result = extract_details_from_text(
            "Responding POV ETA 1000.",
            base_time=base_time,
        )

    assert result["minutes_until_arrival"] == 125
    assert result["correction_applied"] is False
    assert call.call_count == 1
