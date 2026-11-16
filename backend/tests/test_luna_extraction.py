from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.llm import _call_llm_only, _derive_eta_fields


def test_extraction_prompt_requires_evidence_for_vehicle(monkeypatch):
    monkeypatch.setattr("app.llm.ENABLE_LLM_MOCK", False)
    monkeypatch.setattr("app.llm.azure_openai_deployment", "gpt-6-luna")
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content='{"vehicle":"Unknown","status":"Responding","eta_iso":"Unknown","confidence":0.8}'), finish_reason="stop")]
    client.chat.completions.create.return_value = response

    result = _call_llm_only("Responding, ETA unknown", datetime(2026, 1, 1, tzinfo=timezone.utc), None, client)

    prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "If no vehicle is mentioned, use \"Unknown\"" in prompt
    assert "default vehicle to \"POV\"" not in prompt
    assert result["vehicle"] == "Unknown"


def test_explicit_unknown_eta_clears_unsubstantiated_model_and_previous_eta():
    fields, _ = _derive_eta_fields(
        "Responding, ETA unknown.",
        {"eta_iso": "2026-01-01T01:00:00Z"},
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "2026-01-01T02:00:00Z",
        "Responding",
    )
    assert fields["eta"] == "Unknown"
    assert fields["eta_timestamp_utc"] is None
