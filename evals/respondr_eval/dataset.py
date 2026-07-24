"""Dataset loading, validation, fingerprinting, and grouped splitting."""

from __future__ import annotations

import hashlib
import json
import random
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable

from .schema import EvalCase


def load_jsonl(path: str | Path, reviewed_only: bool = False) -> list[EvalCase]:
    dataset_path = Path(path)
    cases: list[EvalCase] = []
    seen: set[str] = set()
    with dataset_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                case = EvalCase.from_dict(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{dataset_path}:{line_number}: {exc}") from exc
            if case.case_id in seen:
                raise ValueError(f"{dataset_path}:{line_number}: duplicate case_id")
            seen.add(case.case_id)
            if not reviewed_only or case.is_reviewed:
                cases.append(case)
    if not cases and not reviewed_only:
        raise ValueError(f"{dataset_path}: dataset is empty")
    return cases


def write_jsonl(path: str | Path, cases: Iterable[EvalCase]) -> None:
    dataset_path = Path(path)
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = [
        json.dumps(case.to_dict(), sort_keys=True, ensure_ascii=False)
        for case in cases
    ]
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=dataset_path.parent,
        prefix=f".{dataset_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write("\n".join(serialized))
        if serialized:
            handle.write("\n")
    temporary.replace(dataset_path)


def fingerprint(cases: Iterable[EvalCase]) -> str:
    digest = hashlib.sha256()
    for case in sorted(cases, key=lambda item: item.case_id):
        digest.update(
            json.dumps(
                case.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def summarize(cases: Iterable[EvalCase]) -> dict[str, object]:
    items = list(cases)
    return {
        "total": len(items),
        "reviewed": sum(item.is_reviewed for item in items),
        "annotation_states": dict(
            sorted(Counter(item.annotation.get("state", "proposed") for item in items).items())
        ),
        "splits": dict(sorted(Counter(item.split for item in items).items())),
        "statuses": dict(
            sorted(Counter(item.reference.status for item in items if item.is_reviewed).items())
        ),
        "vehicles": dict(
            sorted(Counter(item.reference.vehicle for item in items if item.is_reviewed).items())
        ),
    }


def assign_grouped_splits(
    cases: list[EvalCase],
    seed: int = 20260723,
    train_ratio: float = 0.6,
    dev_ratio: float = 0.2,
) -> list[EvalCase]:
    if train_ratio <= 0 or dev_ratio < 0 or train_ratio + dev_ratio >= 1:
        raise ValueError("Split ratios must leave a non-empty test allocation")

    reviewed = [case for case in cases if case.is_reviewed]
    groups: dict[str, list[EvalCase]] = {}
    for case in reviewed:
        group = str(
            case.provenance.get("mission_hash")
            or case.provenance.get("group_hash")
            or case.case_id
        )
        groups.setdefault(group, []).append(case)

    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    if len(keys) >= 3:
        train_count = max(1, round(len(keys) * train_ratio))
        dev_count = max(1, round(len(keys) * dev_ratio))
        if train_count + dev_count >= len(keys):
            train_count = max(1, len(keys) - 2)
            dev_count = 1
        train_end = train_count
        dev_end = train_count + dev_count
    elif len(keys) == 2:
        train_end = 1
        dev_end = 1
    else:
        train_end = len(keys)
        dev_end = len(keys)

    assignments: dict[str, str] = {}
    for index, key in enumerate(keys):
        if index < train_end:
            assignments[key] = "train"
        elif index < dev_end:
            assignments[key] = "dev"
        else:
            assignments[key] = "test"

    for key, grouped_cases in groups.items():
        for case in grouped_cases:
            case.split = assignments[key]
    return cases
