import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from simulator.generator_benchmark import (  # noqa: E402
    control_accuracy,
    load_private_corpus,
    render_html,
    split_by_mission,
)
from simulator.synthetic_messages import (  # noqa: E402
    AIMessageGenerator,
    CorpusMessage,
    HeuristicMessageGenerator,
    MessageRequest,
    NgramMessageGenerator,
)


def request(**overrides):
    values = {
        "request_id": "request-1",
        "team": "K9",
        "status": "Responding",
        "vehicle": "POV",
        "eta_mode": "relative",
        "eta_minutes": 20,
    }
    values.update(overrides)
    return MessageRequest(**values)


def test_heuristic_honors_requested_controls():
    generator = HeuristicMessageGenerator(seed=17)
    controlled = generator.generate(request())
    minimal = generator.generate(
        request(
            request_id="request-2",
            team="IMT",
            vehicle="Unknown",
            eta_mode="none",
        )
    )

    assert "K9" in controlled.text
    assert "POV" in controlled.text
    assert "20 min" in controlled.text
    assert minimal.text == "Responding"
    assert control_accuracy(
        [
            request(),
            request(
                request_id="request-2",
                team="IMT",
                vehicle="Unknown",
                eta_mode="none",
            ),
        ],
        [controlled, minimal],
    ) == 1.0


def test_bigram_model_does_not_learn_personal_tokens():
    generator = NgramMessageGenerator(seed=22)
    generator.fit(
        [
            CorpusMessage(
                team="K9",
                status="Responding",
                vehicle="POV",
                text="Taylor responding with K9 from 47.123,-122.456",
                mission_hash="mission-a",
            ),
            CorpusMessage(
                team="K9",
                status="Responding",
                vehicle="POV",
                text="Handler responding POV ETA 20 minutes",
                mission_hash="mission-b",
            ),
        ]
    )

    result = generator.generate(request())

    assert "Taylor" not in result.text
    assert "47.123" not in result.text
    assert "POV" in result.text


class FakeCompletions:
    def create(self, **kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        messages = []
        for index, item in enumerate(payload["requests"]):
            text = "Responding POV ETA 20 min"
            if index == 1:
                text = "Call 360-555-1212"
            messages.append(
                {"request_id": item["request_id"], "text": text}
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"messages": messages})
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )


def test_ai_generator_replaces_personal_data_with_safe_fallback():
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    generator = AIMessageGenerator(
        client=client,
        deployment="test-deployment",
        model_id="test-model",
    )

    results = generator.generate_batch(
        [request(), request(request_id="request-2")]
    )

    assert results[0].error is None
    assert results[1].error is None
    assert "360-555-1212" not in results[1].text
    assert results[1].metadata["repaired_with"] == "heuristic"
    assert results[1].metadata["repair_reason"] == "pii_detected"


def test_private_corpus_loader_maps_groups_without_exporting_text(tmp_path):
    salt = "test-salt"
    local = tmp_path / "local"
    local.mkdir()
    (local / ".sampling_salt").write_text(salt, encoding="utf-8")
    group_hash = hashlib.sha256(
        f"{salt}:1596896".encode("utf-8")
    ).hexdigest()[:16]
    row = {
        "input": {"text": "Synthetic private fixture"},
        "reference": {
            "status": "Informational",
            "vehicle": "Unknown",
            "eta_iso": "Unknown",
        },
        "provenance": {
            "group_hash": group_hash,
            "mission_hash": "mission-a",
        },
    }
    corpus_path = local / "corpus.jsonl"
    corpus_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    messages = load_private_corpus(corpus_path)

    assert len(messages) == 1
    assert messages[0].team == "K9"
    assert messages[0].text == "Synthetic private fixture"


def test_mission_split_has_no_mission_overlap():
    messages = [
        CorpusMessage("ASAR", "Responding", "POV", "Responding", f"m-{i}")
        for i in range(10)
    ]

    train, test = split_by_mission(messages, 0.2, 5)

    assert {item.mission_hash for item in train}.isdisjoint(
        {item.mission_hash for item in test}
    )
    assert len(test) == 2


def test_html_report_contains_only_supplied_safe_content():
    report = {
        "generated_at": "2026-07-24T00:00:00Z",
        "corpus": {"message_count": 10, "mission_count": 2},
        "split": {"train_messages": 8, "test_messages": 2},
        "calibration": {
            "real_holdout_team_accuracy": 0.5,
            "real_holdout_status_accuracy": 0.75,
        },
        "limitations": ["Use a sealed test."],
        "methods": [
            {
                "name": "heuristic",
                "passes_target": False,
                "metrics": {
                    "composite_score": 0.5,
                    "control_accuracy": 1.0,
                    "team_accuracy": 0.5,
                    "status_accuracy": 0.75,
                    "team_similarity": 0.4,
                    "length_fit": 0.8,
                    "unique_rate": 0.9,
                    "exact_copy_rate": 0.0,
                    "fivegram_overlap_rate": 0.0,
                    "failure_rate": 0.0,
                    "repair_rate": 0.0,
                    "mean_latency_ms": 0.01,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
                "samples": {"ASAR": ["Ground responder en route"]},
            }
        ],
    }

    page = render_html(report)

    assert "SAR message generator benchmark" in page
    assert "Ground responder en route" in page
    assert "inline JSON" not in page
