from respondr_eval.metrics import (
    evaluate_predictions,
    meets_thresholds,
    paired_comparison,
)
from respondr_eval.schema import EvalCase, ReferenceLabel
from respondr_eval.strategies.base import Prediction


def _case(case_id: str, label: ReferenceLabel) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        input={
            "text": "synthetic",
            "base_time": "2026-07-21T00:00:00Z",
            "previous_messages": [],
        },
        reference=label,
        annotation={"state": "approved"},
        split="test",
    )


def test_metrics_cover_exact_eta_tolerance_and_failures():
    cases = [
        _case("one", ReferenceLabel("Responding", "POV", "2026-07-21T00:10:00Z")),
        _case("two", ReferenceLabel("Available", "Unknown", "Unknown")),
        _case("three", ReferenceLabel("Unknown", "Unknown", "Unknown")),
    ]
    predictions = [
        Prediction("Responding", "POV", "2026-07-21T00:14:00Z", input_tokens=10),
        Prediction("Available", "Unknown", "Unknown", output_tokens=5),
        Prediction(error="bad schema"),
    ]

    metrics, rows = evaluate_predictions(
        cases,
        predictions,
        eta_tolerance_minutes=5,
        status_error_weights={"Unknown": {"Error": 4}},
    )

    assert metrics["exact_match_accuracy"] == 2 / 3
    assert metrics["eta_mae_minutes"] == 4
    assert metrics["schema_failure_rate"] == 1 / 3
    assert metrics["input_tokens"] == 10
    assert metrics["output_tokens"] == 5
    assert metrics["status_weighted_error_per_case"] == 4 / 3
    assert metrics["status_responding_recall"] == 1.0
    assert len(rows) == 3


def test_thresholds_and_paired_comparison():
    passed, failures = meets_thresholds(
        {"accuracy": 0.9, "failure_rate": 0.01},
        {"accuracy": {"min": 0.8}, "failure_rate": {"max": 0.02}},
    )
    assert passed
    assert failures == []

    comparison = paired_comparison(
        [
            {"case_id": "a", "exact_match": False},
            {"case_id": "b", "exact_match": True},
        ],
        [
            {"case_id": "a", "exact_match": True},
            {"case_id": "b", "exact_match": True},
        ],
    )
    assert comparison["wins"] == 1
    assert comparison["losses"] == 0
    assert comparison["exact_match_delta"] == 0.5
