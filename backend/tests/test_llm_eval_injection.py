from datetime import datetime, timezone
from unittest.mock import patch

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
