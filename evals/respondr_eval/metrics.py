"""Operational extraction metrics and paired experiment comparisons."""

from __future__ import annotations

import math
import random
import re
from collections import defaultdict
from datetime import datetime
from statistics import mean
from typing import Any, Callable, Iterable

from .schema import EvalCase, VALID_STATUSES
from .strategies.base import Prediction


def _eta_minutes(expected: str, actual: str) -> float | None:
    if expected == "Unknown" or actual == "Unknown":
        return None
    expected_dt = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    actual_dt = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    return abs((actual_dt - expected_dt).total_seconds()) / 60


def _macro_f1(expected: list[str], actual: list[str]) -> float:
    labels = [label for label in VALID_STATUSES if label in expected or label in actual]
    if not labels:
        return 0.0
    scores: list[float] = []
    for label in labels:
        true_positive = sum(e == label and a == label for e, a in zip(expected, actual))
        false_positive = sum(e != label and a == label for e, a in zip(expected, actual))
        false_negative = sum(e == label and a != label for e, a in zip(expected, actual))
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        scores.append(
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
    return mean(scores)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _bootstrap_ci(
    rows: list[dict[str, Any]],
    metric: Callable[[list[dict[str, Any]]], float],
    seed: int = 20260723,
    samples: int = 1000,
) -> list[float]:
    if not rows:
        return [0.0, 0.0]
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        estimates.append(metric(sample))
    return [_percentile(estimates, 0.025), _percentile(estimates, 0.975)]


def evaluate_predictions(
    cases: list[EvalCase],
    predictions: list[Prediction],
    eta_tolerance_minutes: int = 5,
    cost_usd: float | None = None,
    status_error_weights: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if len(cases) != len(predictions):
        raise ValueError("cases and predictions must have the same length")

    rows: list[dict[str, Any]] = []
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for case, prediction in zip(cases, predictions):
        expected = case.reference
        failed = bool(prediction.error)
        status_correct = not failed and prediction.status == expected.status
        vehicle_correct = not failed and prediction.vehicle == expected.vehicle
        expected_eta_present = expected.eta_iso != "Unknown"
        actual_eta_present = not failed and prediction.eta_iso != "Unknown"
        eta_presence_correct = expected_eta_present == actual_eta_present
        eta_error = (
            _eta_minutes(expected.eta_iso, prediction.eta_iso)
            if expected_eta_present and actual_eta_present
            else None
        )
        eta_correct = (
            eta_presence_correct
            if not expected_eta_present
            else eta_error is not None and eta_error <= eta_tolerance_minutes
        )
        exact = status_correct and vehicle_correct and eta_correct
        actual_status = prediction.status if not failed else "Error"
        confusion[expected.status][actual_status] += 1
        status_error_weight = 0.0
        if not status_correct:
            status_error_weight = float(
                (status_error_weights or {})
                .get(expected.status, {})
                .get(actual_status, 1.0)
            )
        rows.append(
            {
                "case_id": case.case_id,
                "status_correct": status_correct,
                "vehicle_correct": vehicle_correct,
                "eta_presence_correct": eta_presence_correct,
                "eta_correct": eta_correct,
                "eta_error_minutes": eta_error,
                "exact_match": exact,
                "latency_ms": prediction.latency_ms,
                "input_tokens": prediction.input_tokens,
                "output_tokens": prediction.output_tokens,
                "retry_count": prediction.retry_count,
                "error": prediction.error,
                "expected_status": expected.status,
                "actual_status": prediction.status if not failed else "Error",
                "expected_vehicle": expected.vehicle,
                "actual_vehicle": prediction.vehicle if not failed else "Error",
                "expected_eta_iso": expected.eta_iso,
                "actual_eta_iso": prediction.eta_iso if not failed else "Error",
                "confidence": prediction.confidence,
                "status_error_weight": status_error_weight,
            }
        )

    count = len(rows)
    exact_accuracy = mean(row["exact_match"] for row in rows) if rows else 0.0
    status_accuracy = mean(row["status_correct"] for row in rows) if rows else 0.0
    vehicle_accuracy = mean(row["vehicle_correct"] for row in rows) if rows else 0.0
    eta_accuracy = mean(row["eta_correct"] for row in rows) if rows else 0.0
    expected_status = [row["expected_status"] for row in rows]
    actual_status = [row["actual_status"] for row in rows]
    eta_errors = [
        row["eta_error_minutes"]
        for row in rows
        if row["eta_error_minutes"] is not None
    ]
    latency = [float(row["latency_ms"]) for row in rows]
    summary = {
        "case_count": count,
        "status_accuracy": status_accuracy,
        "status_macro_f1": _macro_f1(expected_status, actual_status),
        "status_weighted_error_per_case": (
            mean(row["status_error_weight"] for row in rows) if rows else 0.0
        ),
        "vehicle_accuracy": vehicle_accuracy,
        "eta_accuracy": eta_accuracy,
        "eta_presence_accuracy": (
            mean(row["eta_presence_correct"] for row in rows) if rows else 0.0
        ),
        "eta_mae_minutes": mean(eta_errors) if eta_errors else None,
        "exact_match_accuracy": exact_accuracy,
        "schema_failure_rate": (
            mean(bool(row["error"]) for row in rows) if rows else 0.0
        ),
        "retry_rate": (
            mean(row["retry_count"] > 0 for row in rows) if rows else 0.0
        ),
        "latency_p50_ms": _percentile(latency, 0.5),
        "latency_p95_ms": _percentile(latency, 0.95),
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
        "cost_usd": cost_usd,
        "cost_per_1000_messages_usd": (
            cost_usd * 1000 / count if cost_usd is not None and count else None
        ),
        "status_confusion": {
            expected: dict(sorted(actual.items()))
            for expected, actual in sorted(confusion.items())
        },
        "status_accuracy_ci95": _bootstrap_ci(
            rows, lambda sample: mean(row["status_correct"] for row in sample)
        ),
        "exact_match_accuracy_ci95": _bootstrap_ci(
            rows, lambda sample: mean(row["exact_match"] for row in sample)
        ),
    }
    for label in VALID_STATUSES:
        true_positive = sum(
            row["expected_status"] == label and row["actual_status"] == label
            for row in rows
        )
        false_positive = sum(
            row["expected_status"] != label and row["actual_status"] == label
            for row in rows
        )
        false_negative = sum(
            row["expected_status"] == label and row["actual_status"] != label
            for row in rows
        )
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        summary[f"status_{slug}_precision"] = precision
        summary[f"status_{slug}_recall"] = recall
        summary[f"status_{slug}_support"] = sum(
            row["expected_status"] == label for row in rows
        )
    return summary, rows


def paired_comparison(
    baseline_rows: Iterable[dict[str, Any]],
    candidate_rows: Iterable[dict[str, Any]],
    seed: int = 20260723,
) -> dict[str, Any]:
    baseline = {row["case_id"]: row for row in baseline_rows}
    candidate = {row["case_id"]: row for row in candidate_rows}
    shared = sorted(set(baseline) & set(candidate))
    deltas = [
        int(candidate[key]["exact_match"]) - int(baseline[key]["exact_match"])
        for key in shared
    ]
    if not deltas:
        return {"shared_cases": 0, "exact_match_delta": None, "delta_ci95": None}
    rng = random.Random(seed)
    estimates = [
        mean(deltas[rng.randrange(len(deltas))] for _ in deltas)
        for _ in range(1000)
    ]
    return {
        "shared_cases": len(shared),
        "wins": sum(delta > 0 for delta in deltas),
        "ties": sum(delta == 0 for delta in deltas),
        "losses": sum(delta < 0 for delta in deltas),
        "exact_match_delta": mean(deltas),
        "delta_ci95": [_percentile(estimates, 0.025), _percentile(estimates, 0.975)],
    }


def meets_thresholds(metrics: dict[str, Any], thresholds: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for metric, rule in thresholds.items():
        value = metrics.get(metric)
        if value is None:
            failures.append(f"{metric}: missing")
            continue
        if "min" in rule and value < rule["min"]:
            failures.append(f"{metric}: {value:.6g} < {rule['min']:.6g}")
        if "max" in rule and value > rule["max"]:
            failures.append(f"{metric}: {value:.6g} > {rule['max']:.6g}")
    return not failures, failures
