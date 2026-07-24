"""Experiment matrix runner."""

from __future__ import annotations

import json
import hashlib
import platform
import subprocess
import sys
from importlib import metadata
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cache import PredictionCache
from .dataset import fingerprint, load_jsonl
from .metrics import (
    evaluate_predictions,
    meets_thresholds,
    paired_comparison,
)
from .pricing import PricingCatalog
from .reporting import write_report
from .schema import EvalCase
from .strategies.base import Prediction, Strategy
from .strategies.classical import ClassicalStrategy
from .strategies.heuristic import HeuristicStrategy
from .strategies.production_llm import ProductionLLMStrategy


def _resolve(base: Path, value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    return str(path if path.is_absolute() else (base / path).resolve())


def _environment(repository_root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    packages = {}
    for name in ("openai", "scikit-learn"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": packages,
        "git_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "git_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def _strategy(
    config: dict[str, Any], base: Path, allow_live_llm: bool
) -> Strategy:
    kind = config["type"]
    name = str(config["name"])
    if kind == "heuristic":
        return HeuristicStrategy(name)
    if kind == "classical":
        return ClassicalStrategy(
            name=name,
            tune=bool(config.get("tune", False)),
            params=config.get("params"),
        )
    if kind == "production_llm":
        if not allow_live_llm:
            raise RuntimeError(
                f"{name}: live LLM calls are disabled; pass --allow-live-llm"
            )
        return ProductionLLMStrategy(
            name=name,
            deployment=str(config.get("deployment") or ""),
            model_id=str(config.get("model_id") or config.get("deployment") or ""),
            prompt_path=_resolve(base, config.get("prompt_path")),
            reasoning_effort=config.get("reasoning_effort"),
            verbosity=config.get("verbosity"),
            max_tokens=config.get("max_tokens"),
        )
    raise ValueError(f"{name}: unsupported strategy type {kind!r}")


def _prediction(
    strategy: Strategy,
    case: EvalCase,
    experiment: dict[str, Any],
    repetition: int,
    dataset_fingerprint: str,
    cache: PredictionCache,
) -> Prediction:
    cache_payload = {
        "dataset": dataset_fingerprint,
        "case_id": case.case_id,
        "input": case.input,
        "experiment": experiment,
        "strategy": strategy.describe(),
        "repetition": repetition,
    }
    if strategy.kind != "production_llm":
        return strategy.predict(case).validated()
    key = cache.key(cache_payload)
    cached = cache.get(key)
    if cached:
        cached.metadata = {**cached.metadata, "cache_hit": True}
        return cached
    prediction = strategy.predict(case).validated()
    cache.put(key, prediction)
    return prediction


def run(config_path: str | Path, allow_live_llm: bool = False) -> tuple[Path, Path]:
    path = Path(config_path).resolve()
    base = path.parent
    config: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    dataset_path = _resolve(base, config.get("dataset"))
    if not dataset_path:
        raise ValueError("Experiment config requires dataset")
    all_cases = load_jsonl(dataset_path, reviewed_only=True)
    dataset_hash = fingerprint(all_cases)
    evaluation_split = str(config.get("evaluation_split") or "test")
    train_cases = [case for case in all_cases if case.split == "train"]
    dev_cases = [case for case in all_cases if case.split == "dev"]
    evaluation_cases = [case for case in all_cases if case.split == evaluation_split]
    if not evaluation_cases:
        raise ValueError(f"No reviewed cases use split {evaluation_split!r}")

    output_dir = _resolve(base, config.get("output_dir") or "../results")
    cache_path = _resolve(base, config.get("cache") or "../cache/predictions.jsonl")
    assert output_dir and cache_path
    cache = PredictionCache(cache_path)

    pricing_path = _resolve(base, config.get("pricing"))
    pricing = PricingCatalog.load(pricing_path) if pricing_path else None
    thresholds = dict(config.get("thresholds") or {})
    eta_tolerance = int(config.get("eta_tolerance_minutes", 5))
    status_error_weights = dict(config.get("status_error_weights") or {})

    experiment_results: list[dict[str, Any]] = []
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    for experiment in config.get("experiments") or []:
        strategy = _strategy(experiment, base, allow_live_llm)
        strategy.fit(train_cases, dev_cases)
        repetitions = max(1, int(experiment.get("repetitions", 1)))
        measured_cases: list[EvalCase] = []
        predictions: list[Prediction] = []
        for repetition in range(repetitions):
            for case in evaluation_cases:
                measured_cases.append(
                    replace(case, case_id=f"{case.case_id}#r{repetition + 1}")
                )
                predictions.append(
                    _prediction(
                        strategy,
                        case,
                        experiment,
                        repetition,
                        dataset_hash,
                        cache,
                    )
                )

        model_id = str(experiment.get("model_id") or "")
        input_tokens = sum(item.input_tokens for item in predictions)
        output_tokens = sum(item.output_tokens for item in predictions)
        cost = (
            pricing.calculate(model_id, input_tokens, output_tokens)
            if pricing and model_id
            else 0.0
            if strategy.kind in {"heuristic", "classical"}
            else None
        )
        metrics, rows = evaluate_predictions(
            measured_cases,
            predictions,
            eta_tolerance_minutes=eta_tolerance,
            cost_usd=cost,
            status_error_weights=status_error_weights,
        )
        passed, failures = meets_thresholds(metrics, thresholds)
        rows_by_name[strategy.name] = rows
        experiment_results.append(
            {
                "name": strategy.name,
                "strategy": strategy.describe(),
                "metrics": metrics,
                "meets_target": passed,
                "target_failures": failures,
                "case_results": rows,
            }
        )

    paired = []
    if experiment_results:
        baseline = experiment_results[0]["name"]
        for candidate in experiment_results[1:]:
            paired.append(
                {
                    "baseline": baseline,
                    "candidate": candidate["name"],
                    "comparison": paired_comparison(
                        rows_by_name[baseline], rows_by_name[candidate["name"]]
                    ),
                }
            )

    eligible = [
        result
        for result in experiment_results
        if result["meets_target"] and result["metrics"]["cost_usd"] is not None
    ]
    selected = (
        min(
            eligible,
            key=lambda item: (
                item["metrics"]["cost_per_1000_messages_usd"],
                -item["metrics"]["exact_match_accuracy"],
                item["metrics"]["latency_p95_ms"],
            ),
        )["name"]
        if eligible
        else None
    )
    run_data = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "experiment_config_fingerprint": hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "environment": _environment(Path(__file__).resolve().parents[2]),
        "dataset": {
            "path": str(Path(dataset_path)),
            "fingerprint": dataset_hash,
            "evaluation_split": evaluation_split,
            "evaluation_case_count": len(evaluation_cases),
            "train_case_count": len(train_cases),
            "dev_case_count": len(dev_cases),
        },
        "eta_tolerance_minutes": eta_tolerance,
        "status_error_weights": status_error_weights,
        "thresholds": thresholds,
        "pricing_effective_date": pricing.effective_date if pricing else None,
        "experiments": experiment_results,
        "paired_comparisons": paired,
        "least_expensive_meeting_target": selected,
    }
    return write_report(output_dir, run_data)
