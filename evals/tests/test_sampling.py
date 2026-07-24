import json

from respondr_eval.sampling import sample_production


def test_sampler_builds_local_candidates_without_names(monkeypatch, tmp_path):
    entities = [
        {
            "PartitionKey": "messages",
            "RowKey": "message-1",
            "created_at": "1784600000",
            "group_id": "group-a",
            "name": "Synthetic Responder",
            "text": "Responding POV ETA 20 minutes",
            "raw_status": "Responding",
            "vehicle": "POV",
            "eta_timestamp_utc": "2026-07-21T00:20:00Z",
            "eta": "17:20",
        },
        {
            "PartitionKey": "messages",
            "RowKey": "message-2",
            "created_at": str(1784600000 + 13 * 3600),
            "group_id": "group-a",
            "name": "Synthetic Responder",
            "text": "Available for the next call",
            "raw_status": "Available",
            "vehicle": "Unknown",
            "eta_timestamp_utc": "Unknown",
            "eta": "Unknown",
        },
    ]
    monkeypatch.setattr(
        "respondr_eval.sampling._query_entities",
        lambda account_name, table_name: entities,
    )
    output = tmp_path / "local" / "labels.jsonl"

    result = sample_production("account", "table", output)

    content = output.read_text(encoding="utf-8")
    assert result["candidate_cases"] == 2
    assert "Synthetic Responder" not in content
    assert "Responding POV ETA 20 minutes" in content
    lines = [json.loads(line) for line in content.splitlines()]
    assert len({line["provenance"]["mission_hash"] for line in lines}) == 2
