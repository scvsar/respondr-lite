"""Benchmark privacy-safe synthetic SAR message generators."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from simulator.synthetic_messages import (
    AIMessageGenerator,
    CorpusMessage,
    GeneratedMessage,
    HeuristicMessageGenerator,
    MessageRequest,
    NgramMessageGenerator,
    TEAM_GROUP_IDS,
    has_eta_mode,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "evals" / "local" / "prod-ground-truth.jsonl"
DEFAULT_CONFIG = Path(__file__).with_name("generator_benchmark_config.json")
DEFAULT_OUTPUT = ROOT / "evals" / "generator-results"

STATUS_CUES = {
    "Responding": re.compile(
        r"\b(responding|en route|heading|leaving|on my way)\b", re.IGNORECASE
    ),
    "Available": re.compile(r"\b(available|standing by)\b", re.IGNORECASE),
    "Not Responding": re.compile(
        r"\b(cannot|can't|unable|unavailable|not responding)\b", re.IGNORECASE
    ),
    "Cancelled": re.compile(
        r"\b(cancel(?:led|ing)?|standing down|10-22)\b", re.IGNORECASE
    ),
}
VEHICLE_CUE = re.compile(
    r"\bpov\b|\bsar(?:\s+rig|[- ]?\d{1,3})\b|\b(?:car|vehicle|rig)\b",
    re.IGNORECASE,
)


def _hash(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:16]


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def _group_map(corpus_path: Path) -> dict[str, str]:
    salt_path = corpus_path.parent / ".sampling_salt"
    if not salt_path.exists():
        raise FileNotFoundError(
            f"The private corpus salt does not exist: {salt_path}"
        )
    salt = salt_path.read_text(encoding="utf-8").strip()
    return {
        _hash(group_id, salt): team
        for group_id, team in TEAM_GROUP_IDS.items()
    }


def load_private_corpus(path: str | Path) -> list[CorpusMessage]:
    """Load private text into memory without copying it to benchmark output."""
    corpus_path = Path(path).resolve()
    groups = _group_map(corpus_path)
    messages: list[CorpusMessage] = []
    with corpus_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            provenance = row.get("provenance") or {}
            group_hash = str(provenance.get("group_hash") or "")
            team = groups.get(group_hash)
            if not team:
                raise ValueError(
                    f"Row {line_number} has an unmapped production group"
                )
            reference = row.get("reference") or {}
            messages.append(
                CorpusMessage(
                    team=team,
                    status=str(reference.get("status") or "Unknown"),
                    vehicle=str(reference.get("vehicle") or "Unknown"),
                    text=str((row.get("input") or {}).get("text") or ""),
                    mission_hash=str(provenance.get("mission_hash") or ""),
                    eta_iso=str(reference.get("eta_iso") or "Unknown"),
                )
            )
    if not messages:
        raise ValueError("The production corpus is empty")
    return messages


def split_by_mission(
    messages: list[CorpusMessage],
    fraction: float,
    split_seed: int,
) -> tuple[list[CorpusMessage], list[CorpusMessage]]:
    missions = sorted({message.mission_hash for message in messages})
    test_count = max(1, round(len(missions) * fraction))
    rng = random.Random(split_seed)
    test_missions = set(rng.sample(missions, test_count))
    train = [
        message for message in messages if message.mission_hash not in test_missions
    ]
    test = [
        message for message in messages if message.mission_hash in test_missions
    ]
    if not train or not test:
        raise ValueError("The mission split produced an empty partition")
    return train, test


def _eta_mode(message: CorpusMessage, index: int) -> str:
    if message.status != "Responding" or message.eta_iso == "Unknown":
        return "none"
    return ("relative", "clock", "military")[index % 3]


def make_requests(
    messages: list[CorpusMessage],
    seed: int,
) -> list[MessageRequest]:
    rng = random.Random(seed)
    requests: list[MessageRequest] = []
    for index, message in enumerate(messages):
        requests.append(
            MessageRequest(
                request_id=f"request-{index + 1:04d}",
                team=message.team,
                status=message.status,
                vehicle=(
                    message.vehicle
                    if message.status == "Responding"
                    else "Unknown"
                ),
                eta_mode=_eta_mode(message, index),
                eta_minutes=rng.choice((10, 15, 20, 25, 30, 40, 45)),
                message_type=(
                    "followup"
                    if message.status in {"Informational", "Unknown"}
                    else "initial_response"
                ),
            )
        )
    return requests


def _vehicle_matches(text: str, vehicle: str) -> bool:
    if vehicle == "Unknown":
        return not VEHICLE_CUE.search(text)
    if vehicle == "SAR Rig":
        return bool(re.search(r"\bsar\s+rig\b", text, re.IGNORECASE))
    if vehicle == "POV":
        return bool(re.search(r"\bpov\b|\b(?:car|personal vehicle)\b", text, re.IGNORECASE))
    number = re.search(r"\d{1,3}", vehicle)
    if number:
        return bool(
            re.search(
                rf"\bsar[- ]?0*{re.escape(number.group(0))}\b",
                text,
                re.IGNORECASE,
            )
        )
    return vehicle.lower() in text.lower()


def _status_matches(text: str, status: str) -> bool:
    explicit = {
        name
        for name, pattern in STATUS_CUES.items()
        if pattern.search(text)
    }
    if status in STATUS_CUES:
        return status in explicit
    return not explicit


def control_accuracy(
    requests: list[MessageRequest],
    results: list[GeneratedMessage],
) -> float:
    by_id = {result.request_id: result for result in results}
    matches = 0
    checks = 0
    for request in requests:
        text = by_id.get(request.request_id, GeneratedMessage(
            request.request_id,
            request.team,
            request.status,
            "",
            "missing",
        )).text
        checks += 1
        matches += int(_status_matches(text, request.status))
        if request.status == "Responding":
            checks += 2
            matches += int(_vehicle_matches(text, request.vehicle))
            matches += int(has_eta_mode(text, request))
    return matches / checks if checks else 0.0


def _fit_classifiers(
    train: list[CorpusMessage],
    test: list[CorpusMessage],
    config: dict[str, Any],
) -> tuple[Any, Any, Any, dict[str, float]]:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score
    except ImportError as exc:
        raise RuntimeError(
            "Install the evaluation ML dependencies before this benchmark"
        ) from exc

    options = config["classifier"]
    vectorizer = TfidfVectorizer(
        analyzer=options["analyzer"],
        ngram_range=(options["ngram_min"], options["ngram_max"]),
        min_df=options["min_df"],
        max_features=options["max_features"],
        sublinear_tf=True,
    )
    train_matrix = vectorizer.fit_transform([message.text for message in train])
    test_matrix = vectorizer.transform([message.text for message in test])
    team_model = LogisticRegression(
        max_iter=options["max_iter"],
        class_weight="balanced",
        random_state=config["seed"],
    ).fit(train_matrix, [message.team for message in train])
    status_model = LogisticRegression(
        max_iter=options["max_iter"],
        class_weight="balanced",
        random_state=config["seed"],
    ).fit(train_matrix, [message.status for message in train])
    calibration = {
        "real_holdout_team_accuracy": float(
            accuracy_score(
                [message.team for message in test],
                team_model.predict(test_matrix),
            )
        ),
        "real_holdout_status_accuracy": float(
            accuracy_score(
                [message.status for message in test],
                status_model.predict(test_matrix),
            )
        ),
    }
    return vectorizer, team_model, status_model, calibration


def _team_similarity(
    train: list[CorpusMessage],
    requests: list[MessageRequest],
    results: list[GeneratedMessage],
    vectorizer: Any,
) -> float:
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity

    by_id = {result.request_id: result for result in results}
    train_matrix = vectorizer.transform([message.text for message in train])
    teams = sorted({message.team for message in train})
    centroids: dict[str, Any] = {}
    for team in teams:
        indices = [
            index for index, message in enumerate(train) if message.team == team
        ]
        centroids[team] = np.asarray(train_matrix[indices].mean(axis=0))
    scores: list[float] = []
    for request in requests:
        result = by_id.get(request.request_id)
        if not result or not result.text or request.team not in centroids:
            scores.append(0.0)
            continue
        vector = vectorizer.transform([result.text])
        scores.append(
            float(cosine_similarity(vector, centroids[request.team])[0, 0])
        )
    return statistics.fmean(scores) if scores else 0.0


def _length_fit(
    test: list[CorpusMessage],
    requests: list[MessageRequest],
    results: list[GeneratedMessage],
) -> float:
    real_by_team: dict[str, list[int]] = defaultdict(list)
    for message in test:
        real_by_team[message.team].append(_word_count(message.text))
    medians = {
        team: max(1.0, statistics.median(values))
        for team, values in real_by_team.items()
    }
    by_id = {result.request_id: result for result in results}
    scores = []
    for request in requests:
        result = by_id.get(request.request_id)
        count = _word_count(result.text) if result else 0
        target = medians.get(request.team, 8.0)
        scores.append(math.exp(-abs(count - target) / target))
    return statistics.fmean(scores) if scores else 0.0


def _copy_metrics(
    corpus: Iterable[CorpusMessage],
    results: list[GeneratedMessage],
) -> tuple[float, float]:
    real_normalized = {
        _normalize(message.text)
        for message in corpus
        if _word_count(message.text) >= 5
    }
    real_fivegrams: set[tuple[str, ...]] = set()
    for message in corpus:
        words = _normalize(message.text).split()
        real_fivegrams.update(
            tuple(words[index : index + 5])
            for index in range(max(0, len(words) - 4))
        )
    eligible = [
        result for result in results if _word_count(result.text) >= 5
    ]
    exact = sum(
        _normalize(result.text) in real_normalized for result in eligible
    )
    generated_fivegrams: list[tuple[str, ...]] = []
    for result in results:
        words = _normalize(result.text).split()
        generated_fivegrams.extend(
            tuple(words[index : index + 5])
            for index in range(max(0, len(words) - 4))
        )
    overlap = sum(
        fivegram in real_fivegrams for fivegram in generated_fivegrams
    )
    return (
        exact / len(eligible) if eligible else 0.0,
        overlap / len(generated_fivegrams) if generated_fivegrams else 0.0,
    )


def score_method(
    name: str,
    train: list[CorpusMessage],
    test: list[CorpusMessage],
    requests: list[MessageRequest],
    results: list[GeneratedMessage],
    vectorizer: Any,
    team_model: Any,
    status_model: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score

    by_id = {result.request_id: result for result in results}
    ordered = [
        by_id.get(
            request.request_id,
            GeneratedMessage(
                request.request_id,
                request.team,
                request.status,
                "",
                name,
                error="missing_result",
            ),
        )
        for request in requests
    ]
    texts = [result.text for result in ordered]
    generated_matrix = vectorizer.transform(texts)
    failures = sum(bool(result.error) or not result.text for result in ordered)
    unique = len({_normalize(text) for text in texts if text})
    exact_copy_rate, fivegram_overlap_rate = _copy_metrics(
        [*train, *test], ordered
    )
    metrics = {
        "failure_rate": failures / len(ordered),
        "control_accuracy": control_accuracy(requests, ordered),
        "team_accuracy": float(
            accuracy_score(
                [request.team for request in requests],
                team_model.predict(generated_matrix),
            )
        ),
        "status_accuracy": float(
            accuracy_score(
                [request.status for request in requests],
                status_model.predict(generated_matrix),
            )
        ),
        "team_similarity": _team_similarity(
            train, requests, ordered, vectorizer
        ),
        "length_fit": _length_fit(test, requests, ordered),
        "unique_rate": unique / len(ordered),
        "exact_copy_rate": exact_copy_rate,
        "fivegram_overlap_rate": fivegram_overlap_rate,
        "mean_latency_ms": statistics.fmean(
            result.latency_ms for result in ordered
        ),
        "input_tokens": sum(result.input_tokens for result in ordered),
        "output_tokens": sum(result.output_tokens for result in ordered),
        "repair_rate": (
            sum(
                result.metadata.get("repaired_with") == "heuristic"
                for result in ordered
            )
            / len(ordered)
        ),
    }
    weights = config["score_weights"]
    composite = sum(metrics[key] * weight for key, weight in weights.items())
    if metrics["exact_copy_rate"] > config["targets"]["exact_copy_rate_max"]:
        composite = 0.0
    metrics["composite_score"] = composite
    targets = config["targets"]
    passes = (
        metrics["failure_rate"] <= targets["failure_rate_max"]
        and metrics["repair_rate"] <= targets["repair_rate_max"]
        and metrics["exact_copy_rate"] <= targets["exact_copy_rate_max"]
        and metrics["control_accuracy"] >= targets["control_accuracy_min"]
        and metrics["unique_rate"] >= targets["unique_rate_min"]
        and metrics["composite_score"] >= targets["composite_score_min"]
    )
    samples: dict[str, list[str]] = defaultdict(list)
    for request, result in zip(requests, ordered):
        if result.text and len(samples[request.team]) < 2:
            samples[request.team].append(result.text)
    return {
        "name": name,
        "passes_target": passes,
        "metrics": metrics,
        "samples": dict(sorted(samples.items())),
        "errors": dict(
            sorted(Counter(
                result.error for result in ordered if result.error
            ).items())
        ),
        "metadata": next(
            (result.metadata for result in ordered if result.metadata),
            {},
        ),
    }


def _generate_ai(
    generator: AIMessageGenerator,
    requests: list[MessageRequest],
    batch_size: int,
) -> list[GeneratedMessage]:
    results: list[GeneratedMessage] = []
    for start in range(0, len(requests), batch_size):
        results.extend(generator.generate_batch(requests[start : start + batch_size]))
    return results


def _team_counts(messages: Iterable[CorpusMessage]) -> dict[str, int]:
    return dict(sorted(Counter(message.team for message in messages).items()))


def run_benchmark(
    corpus_path: str | Path,
    config_path: str | Path = DEFAULT_CONFIG,
    include_ai: bool = False,
    ai_generator: AIMessageGenerator | None = None,
    ai_batch_size: int = 10,
) -> dict[str, Any]:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    corpus = load_private_corpus(corpus_path)
    train, test = split_by_mission(
        corpus,
        config["test_mission_fraction"],
        config["split_seed"],
    )
    requests = make_requests(test, config["seed"])
    vectorizer, team_model, status_model, calibration = _fit_classifiers(
        train, test, config
    )
    generated: list[tuple[str, list[GeneratedMessage]]] = []
    heuristic = HeuristicMessageGenerator(seed=config["seed"])
    generated.append(("heuristic", heuristic.generate_batch(requests)))
    ml = NgramMessageGenerator(seed=config["seed"])
    ml.fit(train)
    generated.append(("ml", ml.generate_batch(requests)))
    if include_ai:
        if ai_generator is None:
            raise ValueError("ai_generator is required when include_ai is true")
        generated.append(
            ("ai", _generate_ai(ai_generator, requests, ai_batch_size))
        )
    methods = [
        score_method(
            name,
            train,
            test,
            requests,
            results,
            vectorizer,
            team_model,
            status_model,
            config,
        )
        for name, results in generated
    ]
    return {
        "schema_version": "1.0",
        "benchmark_id": config["benchmark_id"],
        "generated_at": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "classification": "development",
        "limitations": [
            "The benchmark settings were developed with aggregate knowledge of this corpus.",
            "Use future production messages for a sealed test.",
            "The classifier metrics measure similarity to private message patterns.",
            "Human review must measure semantic plausibility before simulator release.",
        ],
        "corpus": {
            "message_count": len(corpus),
            "mission_count": len({message.mission_hash for message in corpus}),
            "team_counts": _team_counts(corpus),
            "contains_raw_messages": False,
        },
        "split": {
            "method": "mission-held-out",
            "split_seed": config["split_seed"],
            "train_messages": len(train),
            "test_messages": len(test),
            "train_missions": len({message.mission_hash for message in train}),
            "test_missions": len({message.mission_hash for message in test}),
            "train_team_counts": _team_counts(train),
            "test_team_counts": _team_counts(test),
        },
        "calibration": calibration,
        "targets": config["targets"],
        "score_weights": config["score_weights"],
        "methods": methods,
    }


def render_html(report: dict[str, Any]) -> str:
    metric_labels = [
        ("composite_score", "Composite"),
        ("control_accuracy", "Control"),
        ("team_accuracy", "Team"),
        ("status_accuracy", "Status"),
        ("team_similarity", "Similarity"),
        ("length_fit", "Length"),
        ("unique_rate", "Unique"),
        ("exact_copy_rate", "Exact copy (5+ words)"),
        ("fivegram_overlap_rate", "5-gram overlap"),
        ("failure_rate", "Failure"),
        ("repair_rate", "Safety repair"),
    ]
    headers = "".join(f"<th>{html.escape(label)}</th>" for _, label in metric_labels)
    headers += "<th>Amortized latency</th><th>Input tokens</th><th>Output tokens</th>"
    rows = []
    for method in report["methods"]:
        cells = "".join(
            f"<td>{method['metrics'][key] * 100:.1f}%</td>"
            for key, _ in metric_labels
        )
        cells += (
            f"<td>{method['metrics']['mean_latency_ms']:.1f} ms</td>"
            f"<td>{method['metrics']['input_tokens']}</td>"
            f"<td>{method['metrics']['output_tokens']}</td>"
        )
        outcome = "Pass" if method["passes_target"] else "Below target"
        rows.append(
            f"<tr><th>{html.escape(method['name'])}</th>"
            f"<td><span class=\"pill\">{outcome}</span></td>{cells}</tr>"
        )
    sample_sections = []
    for method in report["methods"]:
        team_cards = []
        for team, samples in method["samples"].items():
            items = "".join(f"<li>{html.escape(sample)}</li>" for sample in samples)
            team_cards.append(
                f"<section><h4>{html.escape(team)}</h4><ul>{items}</ul></section>"
            )
        sample_sections.append(
            f"<details><summary>{html.escape(method['name'])} samples</summary>"
            f"<div class=\"sample-grid\">{''.join(team_cards)}</div></details>"
        )
    limits = "".join(
        f"<li>{html.escape(item)}</li>" for item in report["limitations"]
    )
    split = report["split"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SAR message generator benchmark</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; background: #071017; color: #e7eef4; }}
main {{ max-width: 1220px; margin: auto; padding: 32px 20px 64px; }}
h1 {{ margin-bottom: 6px; }} .muted {{ color: #9aabb7; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap: 12px; margin: 24px 0; }}
.card, details, section {{ background: #111d25; border: 1px solid #293946; border-radius: 12px; padding: 16px; }}
.value {{ font-size: 1.7rem; font-weight: 700; }}
.table-wrap {{ overflow-x: auto; background: #111d25; border: 1px solid #293946; border-radius: 12px; }}
table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
th, td {{ padding: 13px; border-bottom: 1px solid #293946; text-align: right; }}
th:first-child {{ text-align: left; }} .pill {{ color: #ffd27b; }}
details {{ margin-top: 14px; }} summary {{ cursor: pointer; font-weight: 700; }}
.sample-grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(250px,1fr)); gap: 10px; margin-top: 14px; }}
.sample-grid section {{ padding: 12px; }} h4 {{ margin: 0 0 8px; }} li {{ margin: 6px 0; }}
</style>
</head>
<body><main>
<h1>SAR message generator benchmark</h1>
<p class="muted">Development benchmark. Generated {html.escape(report["generated_at"])}.</p>
<div class="cards">
<div class="card"><div class="muted">Production messages</div><div class="value">{report["corpus"]["message_count"]}</div></div>
<div class="card"><div class="muted">Missions</div><div class="value">{report["corpus"]["mission_count"]}</div></div>
<div class="card"><div class="muted">Training messages</div><div class="value">{split["train_messages"]}</div></div>
<div class="card"><div class="muted">Test requests</div><div class="value">{split["test_messages"]}</div></div>
</div>
<h2>Method comparison</h2>
<div class="table-wrap"><table><thead><tr><th>Method</th><th>Target</th>{headers}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="muted">The team classifier scored {report["calibration"]["real_holdout_team_accuracy"] * 100:.1f}% on real held-out messages. The status classifier scored {report["calibration"]["real_holdout_status_accuracy"] * 100:.1f}%.</p>
<h2>Synthetic samples</h2>
{''.join(sample_sections)}
<h2>Limits</h2><ul>{limits}</ul>
</main></body></html>"""


def write_report(report: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "message-generator-benchmark.json"
    html_path = output / "message-generator-benchmark.html"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(render_html(report), encoding="utf-8")
    return json_path, html_path


def _ai_from_environment(args: argparse.Namespace) -> AIMessageGenerator:
    import os

    try:
        from openai import AzureOpenAI
    except ImportError as exc:
        raise RuntimeError("Install the OpenAI package to run the AI method") from exc
    endpoint = args.azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", "")
    api_key = args.azure_api_key or os.getenv("AZURE_OPENAI_API_KEY", "")
    api_version = args.azure_api_version or os.getenv(
        "AZURE_OPENAI_API_VERSION", "2024-12-01-preview"
    )
    deployment = args.azure_deployment or os.getenv(
        "AZURE_OPENAI_DEPLOYMENT_NAME",
        os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
    )
    if not endpoint or not api_key or not deployment:
        raise ValueError(
            "Azure endpoint, API key, and deployment are required for AI generation"
        )
    client = AzureOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        api_version=api_version,
    )
    return AIMessageGenerator(
        client=client,
        deployment=deployment,
        model_id=args.model_id or deployment,
        reasoning_effort=args.reasoning_effort,
        verbosity=args.verbosity,
        max_tokens=args.max_tokens,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare synthetic SAR message generators."
    )
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--include-ai", action="store_true")
    parser.add_argument("--azure-endpoint")
    parser.add_argument("--azure-api-key")
    parser.add_argument("--azure-api-version")
    parser.add_argument("--azure-deployment")
    parser.add_argument("--model-id")
    parser.add_argument("--reasoning-effort", default="minimal")
    parser.add_argument("--verbosity", default="low")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--ai-batch-size", type=int, default=10)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    ai_generator = _ai_from_environment(args) if args.include_ai else None
    report = run_benchmark(
        corpus_path=args.corpus,
        config_path=args.config,
        include_ai=args.include_ai,
        ai_generator=ai_generator,
        ai_batch_size=args.ai_batch_size,
    )
    json_path, html_path = write_report(report, args.output)
    summary = {
        method["name"]: {
            "composite_score": round(
                method["metrics"]["composite_score"], 4
            ),
            "passes_target": method["passes_target"],
        }
        for method in report["methods"]
    }
    print(json.dumps(summary, sort_keys=True))
    print(f"JSON report: {json_path}")
    print(f"HTML report: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
