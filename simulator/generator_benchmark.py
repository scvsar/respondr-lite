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
    RetrievalSlotMessageGenerator,
    TEAM_GROUP_IDS,
    has_eta_mode,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "evals" / "local" / "prod-ground-truth.jsonl"
DEFAULT_CONFIG = Path(__file__).with_name("generator_benchmark_config_v2.json")
DEFAULT_OUTPUT = ROOT / "evals" / "generator-results" / "v2"

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


def _corrupt_text(text: str, rng: random.Random) -> str:
    words = re.findall(r"\b[\w'-]+\b", text)
    if len(words) < 3:
        return " ".join([*words, "the", "of"])
    corrupted = list(words)
    rng.shuffle(corrupted)
    if corrupted == words:
        corrupted = corrupted[1:] + corrupted[:1]
    if len(corrupted) >= 5:
        insert_at = rng.randrange(1, len(corrupted))
        corrupted.insert(insert_at, rng.choice(("the", "in", "of", "at")))
    return " ".join(corrupted)


def _fit_fluency_classifier(
    train: list[CorpusMessage],
    test: list[CorpusMessage],
    config: dict[str, Any],
) -> tuple[Any, Any, dict[str, float]]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    options = config.get("fluency_classifier") or {
        "ngram_min": 1,
        "ngram_max": 2,
        "min_df": 2,
        "max_features": 12000,
        "max_iter": 2000,
        "accept_probability": 0.5,
    }
    rng = random.Random(config["seed"])
    real_train = [message.text for message in train]
    corrupt_train = [
        _corrupt_text(message.text, rng)
        for message in train
    ]
    vectorizer = TfidfVectorizer(
        analyzer="word",
        ngram_range=(options["ngram_min"], options["ngram_max"]),
        min_df=options["min_df"],
        max_features=options["max_features"],
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform([*real_train, *corrupt_train])
    labels = [1] * len(real_train) + [0] * len(corrupt_train)
    model = LogisticRegression(
        max_iter=options["max_iter"],
        class_weight="balanced",
        random_state=config["seed"],
    ).fit(matrix, labels)
    threshold = float(options["accept_probability"])
    real_probabilities = model.predict_proba(
        vectorizer.transform([message.text for message in test])
    )[:, 1]
    corrupt_test = [
        _corrupt_text(message.text, rng)
        for message in test
    ]
    corrupt_probabilities = model.predict_proba(
        vectorizer.transform(corrupt_test)
    )[:, 1]
    calibration = {
        "real_holdout_fluency_accept_rate": float(
            (real_probabilities >= threshold).mean()
        ),
        "corrupt_holdout_reject_rate": float(
            (corrupt_probabilities < threshold).mean()
        ),
        "fluency_accept_probability": threshold,
    }
    return vectorizer, model, calibration


def _status_labels(text: str) -> set[str]:
    labels: set[str] = set()
    if re.search(
        r"\b(cancel(?:led|ing)?|standing down|10-22)\b",
        text,
        re.IGNORECASE,
    ):
        labels.add("Cancelled")
    if re.search(
        r"\b(cannot|can't|unable|unavailable|not responding)\b",
        text,
        re.IGNORECASE,
    ):
        labels.add("Not Responding")
    if re.search(r"\b(available|standing by)\b", text, re.IGNORECASE):
        labels.add("Available")
    without_negative = re.sub(
        r"\b(?:not responding|cannot respond|can't respond|unable to respond)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if re.search(
        r"\b(responding|en route|heading|leaving|on my way)\b",
        without_negative,
        re.IGNORECASE,
    ):
        labels.add("Responding")
    return labels


def _vehicle_values(text: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(
        r"\bpov\b|\b(?:car|personal vehicle)\b|"
        r"\bsar\s+rig\b|\bsar[- ]?0*(\d{1,3})\b",
        text,
        re.IGNORECASE,
    ):
        value = match.group(0).lower()
        if match.group(1):
            value = f"sar-{int(match.group(1))}"
        elif "rig" in value:
            value = "sar rig"
        elif value in {"car", "personal vehicle", "pov"}:
            value = "pov"
        values.append(value)
    return values


def _eta_values(text: str) -> list[str]:
    values: list[str] = []
    occupied: list[tuple[int, int]] = []
    patterns = (
        re.compile(r"\b\d{1,3}\s*(?:min|minute|minutes)\b", re.IGNORECASE),
        re.compile(
            r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[ap]\.?m\.?)?\b",
            re.IGNORECASE,
        ),
        re.compile(r"(?<![-\d])(?:[01]\d|2[0-3])[0-5]\d(?!\d)"),
    )
    for pattern in patterns:
        for match in pattern.finditer(text):
            if any(
                start < match.end() and match.start() < end
                for start, end in occupied
            ):
                continue
            occupied.append(match.span())
            values.append(match.group(0).lower())
    return values


def message_semantically_valid(text: str, request: MessageRequest) -> bool:
    labels = _status_labels(text)
    if request.status in {
        "Responding",
        "Available",
        "Not Responding",
        "Cancelled",
    }:
        if labels != {request.status}:
            return False
    elif labels:
        return False
    vehicles = _vehicle_values(text)
    eta_values = _eta_values(text)
    if request.status != "Responding":
        return not vehicles and not eta_values
    if len(vehicles) > 1 or not _vehicle_matches(text, request.vehicle):
        return False
    if request.vehicle == "Unknown" and vehicles:
        return False
    if request.vehicle != "Unknown" and len(vehicles) != 1:
        return False
    if len(eta_values) > 1 or not has_eta_mode(text, request):
        return False
    if request.eta_mode == "none" and eta_values:
        return False
    if request.eta_mode != "none" and len(eta_values) != 1:
        return False
    return True


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
    fluency_vectorizer: Any,
    fluency_model: Any,
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
    raw_texts = [
        str(
            result.metadata["raw_text_before_repair"]
            if "raw_text_before_repair" in result.metadata
            else result.text
        )
        for result in ordered
    ]
    generated_matrix = vectorizer.transform(texts)
    fluency_probabilities = fluency_model.predict_proba(
        fluency_vectorizer.transform(texts)
    )[:, 1]
    raw_results = [
        GeneratedMessage(
            request_id=result.request_id,
            team=result.team,
            status=result.status,
            text=raw_text,
            strategy=result.strategy,
        )
        for result, raw_text in zip(ordered, raw_texts)
    ]
    raw_fluency_probabilities = fluency_model.predict_proba(
        fluency_vectorizer.transform(raw_texts)
    )[:, 1]
    fluency_threshold = float(
        (config.get("fluency_classifier") or {}).get(
            "accept_probability", 0.5
        )
    )
    failures = sum(bool(result.error) or not result.text for result in ordered)
    unique = len({_normalize(text) for text in texts if text})
    exact_copy_rate, fivegram_overlap_rate = _copy_metrics(
        [*train, *test], ordered
    )
    metrics = {
        "failure_rate": failures / len(ordered),
        "control_accuracy": control_accuracy(requests, ordered),
        "raw_control_accuracy": control_accuracy(requests, raw_results),
        "semantic_validity": (
            sum(
                message_semantically_valid(result.text, request)
                for request, result in zip(requests, ordered)
            )
            / len(ordered)
        ),
        "raw_semantic_validity": (
            sum(
                message_semantically_valid(raw_text, request)
                for request, raw_text in zip(requests, raw_texts)
            )
            / len(ordered)
        ),
        "fluency_accept_rate": float(
            (fluency_probabilities >= fluency_threshold).mean()
        ),
        "raw_fluency_accept_rate": float(
            (raw_fluency_probabilities >= fluency_threshold).mean()
        ),
        "mean_fluency_probability": float(fluency_probabilities.mean()),
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
        "fallback_rate": (
            sum(
                result.metadata.get("fallback") == "heuristic"
                for result in ordered
            )
            / len(ordered)
        ),
    }
    weights = config["score_weights"]
    composite = sum(metrics[key] * weight for key, weight in weights.items())
    if (
        config.get("zero_composite_on_exact_copy", True)
        and metrics["exact_copy_rate"]
        > config["targets"]["exact_copy_rate_max"]
    ):
        composite = 0.0
    metrics["composite_score"] = composite
    targets = config["targets"]
    passes = (
        metrics["failure_rate"] <= targets["failure_rate_max"]
        and metrics["repair_rate"] <= targets["repair_rate_max"]
        and metrics["fallback_rate"]
        <= targets.get("fallback_rate_max", 1.0)
        and metrics["exact_copy_rate"] <= targets["exact_copy_rate_max"]
        and metrics["control_accuracy"] >= targets["control_accuracy_min"]
        and metrics["semantic_validity"]
        >= targets.get("semantic_validity_min", 0.0)
        and metrics["fluency_accept_rate"]
        >= targets.get("fluency_accept_rate_min", 0.0)
        and metrics["unique_rate"] >= targets["unique_rate_min"]
        and metrics["raw_control_accuracy"]
        >= targets.get("raw_control_accuracy_min", 0.0)
        and metrics["raw_semantic_validity"]
        >= targets.get("raw_semantic_validity_min", 0.0)
        and metrics["raw_fluency_accept_rate"]
        >= targets.get("raw_fluency_accept_rate_min", 0.0)
        and metrics["composite_score"] >= targets["composite_score_min"]
    )
    samples: dict[str, list[dict[str, str]]] = defaultdict(list)
    for request, result in zip(requests, ordered):
        if result.text and len(samples[request.team]) < 2:
            source = name
            if result.metadata.get("repaired_with") == "heuristic":
                source = "heuristic safety repair"
            elif result.metadata.get("fallback") == "heuristic":
                source = "heuristic fallback"
            samples[request.team].append(
                {
                    "text": result.text,
                    "raw_text": str(
                        result.metadata.get("raw_text_before_repair") or ""
                    ),
                    "repair_reason": str(
                        result.metadata.get("repair_reason") or ""
                    ),
                    "source": source,
                    "requested_status": request.status,
                    "requested_vehicle": request.vehicle,
                    "requested_eta_mode": request.eta_mode,
                }
            )
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
    ai_generators: dict[str, AIMessageGenerator] | None = None,
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
    (
        fluency_vectorizer,
        fluency_model,
        fluency_calibration,
    ) = _fit_fluency_classifier(train, test, config)
    calibration.update(fluency_calibration)
    generated: list[tuple[str, list[GeneratedMessage]]] = []
    generated_by_name: dict[str, list[GeneratedMessage]] = {}
    method_names = config.get("methods") or ["heuristic", "ml", "ai"]
    retrieval_metadata: dict[str, Any] | None = None
    for method_name in method_names:
        if method_name == "heuristic":
            heuristic = HeuristicMessageGenerator(seed=config["seed"])
            generated.append(
                ("heuristic", heuristic.generate_batch(requests))
            )
        elif method_name in {"ml", "ml-bigram"}:
            ml = NgramMessageGenerator(seed=config["seed"])
            ml.fit(train)
            generated.append(
                (
                    "ml-bigram" if method_name == "ml-bigram" else "ml",
                    ml.generate_batch(requests),
                )
            )
        elif method_name == "ml-retrieval":
            retrieval = RetrievalSlotMessageGenerator(seed=config["seed"])
            retrieval.fit(train)
            generated.append(
                ("ml-retrieval", retrieval.generate_batch(requests))
            )
            retrieval_metadata = {
                "training_messages": retrieval.training_count,
                "accepted_templates": retrieval.template_count,
            }
        elif method_name in {
            "ai",
            "ai-current",
            "ai-context-v2",
        } and include_ai:
            selected = (ai_generators or {}).get(method_name)
            if selected is None and method_name == "ai":
                selected = ai_generator
            if selected is None:
                raise ValueError(
                    f"An AI generator is required for {method_name}"
                )
            results = _generate_ai(selected, requests, ai_batch_size)
            generated.append((method_name, results))
            generated_by_name[method_name] = results
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
            fluency_vectorizer,
            fluency_model,
            config,
        )
        for name, results in generated
    ]
    if retrieval_metadata:
        next(
            method for method in methods if method["name"] == "ml-retrieval"
        )["training"] = retrieval_metadata
    report = {
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
            "The fluency classifier is a proxy and can accept malformed text.",
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
        "requires_human_review": bool(
            config.get("requires_human_review", False)
        ),
        "methods": methods,
    }
    if {
        "ai-current",
        "ai-context-v2",
    }.issubset(generated_by_name):
        report["paired_prompt_comparison"] = paired_prompt_comparison(
            requests,
            generated_by_name["ai-current"],
            generated_by_name["ai-context-v2"],
        )
    return report


def paired_prompt_comparison(
    requests: list[MessageRequest],
    current: list[GeneratedMessage],
    candidate: list[GeneratedMessage],
) -> dict[str, int]:
    """Compare prompt results for the same requests before safety repair."""
    current_by_id = {result.request_id: result for result in current}
    candidate_by_id = {result.request_id: result for result in candidate}
    counts = Counter()
    for request in requests:
        current_result = current_by_id[request.request_id]
        candidate_result = candidate_by_id[request.request_id]
        current_raw = str(
            current_result.metadata["raw_text_before_repair"]
            if "raw_text_before_repair" in current_result.metadata
            else current_result.text
        )
        candidate_raw = str(
            candidate_result.metadata["raw_text_before_repair"]
            if "raw_text_before_repair" in candidate_result.metadata
            else candidate_result.text
        )
        current_valid = message_semantically_valid(current_raw, request)
        candidate_valid = message_semantically_valid(candidate_raw, request)
        if current_valid and candidate_valid:
            counts["both_valid"] += 1
        elif current_valid:
            counts["candidate_regressions"] += 1
        elif candidate_valid:
            counts["candidate_improvements"] += 1
        else:
            counts["both_invalid"] += 1
        current_repaired = bool(
            current_result.metadata.get("repaired_with")
        )
        candidate_repaired = bool(
            candidate_result.metadata.get("repaired_with")
        )
        if current_repaired and not candidate_repaired:
            counts["repairs_avoided"] += 1
        elif not current_repaired and candidate_repaired:
            counts["new_repairs"] += 1
    return {
        key: int(counts[key])
        for key in (
            "both_valid",
            "candidate_improvements",
            "candidate_regressions",
            "both_invalid",
            "repairs_avoided",
            "new_repairs",
        )
    }


def render_html(report: dict[str, Any]) -> str:
    metric_labels = [
        ("composite_score", "Composite"),
        ("control_accuracy", "Control"),
        ("semantic_validity", "Semantic validity"),
        ("fluency_accept_rate", "Fluency"),
        ("raw_control_accuracy", "Raw control"),
        ("raw_semantic_validity", "Raw semantic"),
        ("raw_fluency_accept_rate", "Raw fluency"),
        ("team_accuracy", "Team"),
        ("status_accuracy", "Status"),
        ("team_similarity", "Similarity"),
        ("length_fit", "Length"),
        ("unique_rate", "Unique"),
        ("exact_copy_rate", "Exact copy (5+ words)"),
        ("fivegram_overlap_rate", "5-gram overlap"),
        ("failure_rate", "Failure"),
        ("repair_rate", "Safety repair"),
        ("fallback_rate", "Fallback"),
    ]
    headers = "".join(f"<th>{html.escape(label)}</th>" for _, label in metric_labels)
    headers += "<th>Amortized latency</th><th>Input tokens</th><th>Output tokens</th>"
    rows = []
    for method in report["methods"]:
        cells = "".join(
            f"<td>{method['metrics'].get(key, 0.0) * 100:.1f}%</td>"
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
            items = ""
            for sample in samples:
                if isinstance(sample, str):
                    text = sample
                    detail = ""
                else:
                    text = sample["text"]
                    detail = (
                        f"{sample['source']} | {sample['requested_status']} | "
                        f"{sample['requested_vehicle']} | "
                        f"ETA {sample['requested_eta_mode']}"
                    )
                    raw_text = sample.get("raw_text") or ""
                    if raw_text and raw_text != text:
                        detail += f" | raw: {raw_text}"
                    if sample.get("repair_reason"):
                        detail += f" | repair: {sample['repair_reason']}"
                items += (
                    f"<li>{html.escape(text)}"
                    f"<div class=\"sample-detail\">{html.escape(detail)}</div></li>"
                )
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
    human_review_notice = (
        '<p class="muted">Human review is required before method selection.</p>'
        if report.get("requires_human_review")
        else ""
    )
    paired = report.get("paired_prompt_comparison")
    paired_section = ""
    if paired:
        paired_section = f"""
<h2>Paired prompt comparison</h2>
<div class="cards">
<div class="card"><div class="muted">Candidate improvements</div><div class="value">{paired["candidate_improvements"]}</div></div>
<div class="card"><div class="muted">Candidate regressions</div><div class="value">{paired["candidate_regressions"]}</div></div>
<div class="card"><div class="muted">Both valid</div><div class="value">{paired["both_valid"]}</div></div>
<div class="card"><div class="muted">Both invalid</div><div class="value">{paired["both_invalid"]}</div></div>
<div class="card"><div class="muted">Repairs avoided</div><div class="value">{paired["repairs_avoided"]}</div></div>
<div class="card"><div class="muted">New repairs</div><div class="value">{paired["new_repairs"]}</div></div>
</div>"""
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
.sample-detail {{ color: #9aabb7; font-size: 0.78rem; margin-top: 3px; }}
</style>
</head>
<body><main>
<h1>SAR message generator benchmark</h1>
<p class="muted">Development benchmark. Generated {html.escape(report["generated_at"])}.</p>
{human_review_notice}
<div class="cards">
<div class="card"><div class="muted">Production messages</div><div class="value">{report["corpus"]["message_count"]}</div></div>
<div class="card"><div class="muted">Missions</div><div class="value">{report["corpus"]["mission_count"]}</div></div>
<div class="card"><div class="muted">Training messages</div><div class="value">{split["train_messages"]}</div></div>
<div class="card"><div class="muted">Test requests</div><div class="value">{split["test_messages"]}</div></div>
</div>
<h2>Method comparison</h2>
<div class="table-wrap"><table><thead><tr><th>Method</th><th>Target</th>{headers}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
{paired_section}
<p class="muted">The team classifier scored {report["calibration"]["real_holdout_team_accuracy"] * 100:.1f}% on real held-out messages. The status classifier scored {report["calibration"]["real_holdout_status_accuracy"] * 100:.1f}%. The fluency check accepted {report["calibration"].get("real_holdout_fluency_accept_rate", 0.0) * 100:.1f}% of real held-out messages and rejected {report["calibration"].get("corrupt_holdout_reject_rate", 0.0) * 100:.1f}% of corrupted messages.</p>
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


def _ai_from_environment(
    args: argparse.Namespace,
    prompt_version: str = AIMessageGenerator.CURRENT_PROMPT_VERSION,
) -> AIMessageGenerator:
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
        prompt_version=prompt_version,
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
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    ai_generator = None
    ai_generators = None
    if args.include_ai:
        methods = set(config.get("methods") or [])
        ai_generators = {}
        if "ai" in methods:
            ai_generator = _ai_from_environment(args)
        if "ai-current" in methods:
            ai_generators["ai-current"] = _ai_from_environment(
                args,
                AIMessageGenerator.CURRENT_PROMPT_VERSION,
            )
        if "ai-context-v2" in methods:
            ai_generators["ai-context-v2"] = _ai_from_environment(
                args,
                AIMessageGenerator.CONTEXT_PROMPT_VERSION,
            )
    report = run_benchmark(
        corpus_path=args.corpus,
        config_path=args.config,
        include_ai=args.include_ai,
        ai_generator=ai_generator,
        ai_generators=ai_generators,
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
