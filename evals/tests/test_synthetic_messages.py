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
    message_semantically_valid,
    paired_prompt_comparison,
    render_html,
    split_by_mission,
)
from simulator.synthetic_messages import (  # noqa: E402
    AIMessageGenerator,
    CorpusMessage,
    GeneratedMessage,
    HeuristicMessageGenerator,
    MessageRequest,
    NgramMessageGenerator,
    RetrievalSlotMessageGenerator,
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


def test_retrieval_model_preserves_structure_and_replaces_slots():
    generator = RetrievalSlotMessageGenerator(seed=23)
    generator.fit(
        [
            CorpusMessage(
                team="K9",
                status="Responding",
                vehicle="POV",
                text="Responding POV ETA 20 minutes",
                mission_hash="mission-a",
            ),
            CorpusMessage(
                team="K9",
                status="Responding",
                vehicle="SAR-6",
                text="Heading to staging in SAR-6, ETA 30 min",
                mission_hash="mission-b",
            ),
            CorpusMessage(
                team="K9",
                status="Responding",
                vehicle="POV",
                text="Taylor responding POV ETA 25 min",
                mission_hash="mission-c",
            ),
        ]
    )

    result = generator.generate(
        request(vehicle="SAR-10", eta_minutes=25)
    )

    assert result.metadata["fallback"] is None
    assert "SAR-10" in result.text
    assert "25 min" in result.text
    assert "Taylor" not in result.text
    assert result.text not in {
        "Responding POV ETA 20 minutes",
        "Heading to staging in SAR-6, ETA 30 min",
    }


class FakeCompletions:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
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
    assert results[1].metadata["raw_text_before_repair"] == ""


def test_ai_prompt_versions_preserve_control_and_add_responder_context():
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    current = AIMessageGenerator(
        client=client,
        deployment="test-deployment",
        model_id="test-model",
    )
    current.generate_batch([request()])
    current_prompt = completions.last_kwargs["messages"][0]["content"]

    candidate = AIMessageGenerator(
        client=client,
        deployment="test-deployment",
        model_id="test-model",
        prompt_version=AIMessageGenerator.CONTEXT_PROMPT_VERSION,
    )
    candidate.generate_batch([request()])
    candidate_prompt = completions.last_kwargs["messages"][0]["content"]

    assert current_prompt.startswith(
        "Generate synthetic Search and Rescue chat messages."
    )
    assert "Write each message as the responder" in candidate_prompt
    assert "Do not invent an assignment" in candidate_prompt
    assert current_prompt != candidate_prompt


class InvalidStatusCompletions:
    def create(self, **kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        messages = [
            {
                "request_id": item["request_id"],
                "text": "Available for field support",
            }
            for item in payload["requests"]
        ]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"messages": messages})
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def test_ai_generator_retains_safe_raw_text_before_repair():
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=InvalidStatusCompletions())
    )
    generator = AIMessageGenerator(
        client=client,
        deployment="test-deployment",
        model_id="test-model",
    )

    result = generator.generate_batch([request()])[0]

    assert result.metadata["repair_reason"] == "status_control"
    assert (
        result.metadata["raw_text_before_repair"]
        == "Available for field support"
    )
    assert result.text != result.metadata["raw_text_before_repair"]


def test_paired_prompt_comparison_counts_raw_improvements_and_repairs():
    item = request()
    current = GeneratedMessage(
        item.request_id,
        item.team,
        item.status,
        "K9 responding POV ETA 20 min",
        "ai-current",
        metadata={
            "raw_text_before_repair": "",
            "repaired_with": "heuristic",
        },
    )
    candidate = GeneratedMessage(
        item.request_id,
        item.team,
        item.status,
        "Responding POV ETA 20 min",
        "ai-context-v2",
        metadata={
            "raw_text_before_repair": "Responding POV ETA 20 min",
        },
    )

    comparison = paired_prompt_comparison(
        [item],
        [current],
        [candidate],
    )

    assert comparison["candidate_improvements"] == 1
    assert comparison["candidate_regressions"] == 0
    assert comparison["repairs_avoided"] == 1


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


def test_semantic_validator_rejects_conflicting_controls():
    valid_request = request(
        vehicle="SAR-10",
        eta_mode="relative",
        eta_minutes=25,
    )

    assert message_semantically_valid(
        "Responding SAR-10 ETA 25 min",
        valid_request,
    )
    assert not message_semantically_valid(
        "Cannot respond. Responding SAR-10 ETA 25 min",
        valid_request,
    )
    assert not message_semantically_valid(
        "Responding SAR-6 SAR-10 ETA 25 min",
        valid_request,
    )
    assert not message_semantically_valid(
        "Responding SAR-10 ETA 2047 ETA 25 min",
        valid_request,
    )


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
                "samples": {
                    "ASAR": [
                        {
                            "text": "Ground responder en route",
                            "source": "ml-retrieval",
                            "requested_status": "Responding",
                            "requested_vehicle": "POV",
                            "requested_eta_mode": "none",
                        }
                    ]
                },
            }
        ],
    }

    page = render_html(report)

    assert "SAR message generator benchmark" in page
    assert "Ground responder en route" in page
    assert "ml-retrieval | Responding | POV | ETA none" in page
    assert "inline JSON" not in page
