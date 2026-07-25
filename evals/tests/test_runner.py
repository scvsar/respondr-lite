import json
from pathlib import Path
from threading import Lock

from respondr_eval.cache import PredictionCache
from respondr_eval.dataset import load_jsonl
from respondr_eval.runner import (
    _dataset_kind,
    _experiment_predictions,
    _paired_comparisons,
    run,
)
from respondr_eval.strategies.base import Prediction


ROOT = Path(__file__).parents[1]


class FakeLiveStrategy:
    kind = "production_llm"
    name = "fake-live"

    def __init__(self):
        self.calls = 0
        self.lock = Lock()

    def describe(self):
        return {"kind": self.kind, "name": self.name}

    def predict(self, case):
        with self.lock:
            self.calls += 1
        return Prediction(
            status=case.reference.status,
            vehicle=case.reference.vehicle,
            eta_iso=case.reference.eta_iso,
        )


def test_live_predictions_use_bounded_concurrency_and_keep_order(tmp_path):
    cases = load_jsonl(ROOT / "data" / "synthetic_seed.jsonl", reviewed_only=True)[:4]
    strategy = FakeLiveStrategy()
    cache = PredictionCache(tmp_path / "cache.jsonl")
    measured, predictions, max_concurrency = _experiment_predictions(
        strategy,
        cases,
        {"name": "fake-live", "type": "production_llm", "max_concurrency": 4},
        repetitions=2,
        dataset_fingerprint="synthetic-test",
        cache=cache,
    )

    assert max_concurrency == 4
    assert [case.case_id for case in measured] == [
        *(f"{case.case_id}#r1" for case in cases),
        *(f"{case.case_id}#r2" for case in cases),
    ]
    assert [prediction.status for prediction in predictions] == [
        *(case.reference.status for case in cases),
        *(case.reference.status for case in cases),
    ]
    assert len((tmp_path / "cache.jsonl").read_text(encoding="utf-8").splitlines()) == 8
    assert strategy.calls == 8

    cached_strategy = FakeLiveStrategy()
    _, cached_predictions, cached_concurrency = _experiment_predictions(
        cached_strategy,
        cases,
        {"name": "fake-live", "type": "production_llm", "max_concurrency": 2},
        repetitions=2,
        dataset_fingerprint="synthetic-test",
        cache=cache,
    )

    assert cached_concurrency == 2
    assert cached_strategy.calls == 0
    assert all(prediction.metadata["cache_hit"] for prediction in cached_predictions)


def test_assumed_production_labels_are_not_reported_as_reviewed():
    cases = load_jsonl(ROOT / "data" / "synthetic_seed.jsonl", reviewed_only=True)
    for case in cases:
        case.annotation["reviewer"] = "assumed-proposal"

    assert _dataset_kind(cases, ["azure_table"]) == "assumed-production"


def test_configured_paired_comparison_can_compare_two_candidates():
    experiment_results = [
        {"name": "heuristic"},
        {"name": "older-model"},
        {"name": "newer-model"},
    ]
    rows_by_name = {
        "heuristic": [{"case_id": "1", "exact_match": False}],
        "older-model": [{"case_id": "1", "exact_match": True}],
        "newer-model": [{"case_id": "1", "exact_match": False}],
    }

    comparisons = _paired_comparisons(
        experiment_results,
        rows_by_name,
        [{"baseline": "older-model", "candidate": "newer-model"}],
    )

    assert comparisons == [
        {
            "baseline": "older-model",
            "candidate": "newer-model",
            "comparison": {
                "shared_cases": 1,
                "wins": 0,
                "ties": 0,
                "losses": 1,
                "exact_match_delta": -1,
                "delta_ci95": [-1, -1],
            },
        }
    ]


def test_example_matrix_writes_private_reports(tmp_path):
    config = json.loads(
        (ROOT / "configs" / "example_experiments.json").read_text(encoding="utf-8")
    )
    config["dataset"] = str(ROOT / "data" / "synthetic_seed.jsonl")
    config["pricing"] = str(ROOT / "configs" / "pricing.example.json")
    config["output_dir"] = str(tmp_path / "results")
    config["cache"] = str(tmp_path / "cache.jsonl")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    json_path, markdown_path = run(path)

    result = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(result["experiments"]) == 2
    assert result["dataset"]["evaluation_case_count"] == 6
    assert result["dataset"]["kind"] == "synthetic"
    assert result["dataset"]["sources"] == ["synthetic"]
    assert result["environment"]["git_commit"]
    assert len(result["experiments"][0]["case_results"]) == 6
    first_case = result["experiments"][0]["case_results"][0]
    assert "expected_vehicle" in first_case
    assert "actual_vehicle" in first_case
    assert "expected_eta_iso" in first_case
    assert "actual_eta_iso" in first_case
    assert "raw responder" in markdown_path.read_text(encoding="utf-8")
    assert "Dataset type: `synthetic`" in markdown_path.read_text(encoding="utf-8")
    assert "Synthetic evaluation cases: 6" in markdown_path.read_text(
        encoding="utf-8"
    )
    assert "Rolling in 45" not in json_path.read_text(encoding="utf-8")
