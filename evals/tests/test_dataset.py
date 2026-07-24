import json
from pathlib import Path

import pytest

from respondr_eval.dataset import (
    assign_grouped_splits,
    fingerprint,
    load_jsonl,
    summarize,
    write_jsonl,
)


SEED = Path(__file__).parents[1] / "data" / "synthetic_seed.jsonl"


def test_seed_dataset_is_valid_and_versioned():
    cases = load_jsonl(SEED)

    summary = summarize(cases)
    assert summary["total"] == 18
    assert summary["reviewed"] == 18
    assert summary["splits"] == {"dev": 4, "test": 6, "train": 8}
    assert len(fingerprint(cases)) == 64


def test_loader_rejects_duplicate_ids(tmp_path):
    line = SEED.read_text(encoding="utf-8").splitlines()[0]
    path = tmp_path / "duplicate.jsonl"
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate case_id"):
        load_jsonl(path)


def test_grouped_split_keeps_missions_together(tmp_path):
    cases = load_jsonl(SEED)
    for case in cases:
        case.split = "unassigned"
    assign_grouped_splits(cases, seed=1)
    write_jsonl(tmp_path / "split.jsonl", cases)

    mission_splits = {}
    for case in cases:
        mission = case.provenance["mission_hash"]
        mission_splits.setdefault(mission, set()).add(case.split)
    assert all(len(splits) == 1 for splits in mission_splits.values())
    assert {"train", "dev", "test"} <= {case.split for case in cases}


def test_loader_requires_timezone(tmp_path):
    raw = json.loads(SEED.read_text(encoding="utf-8").splitlines()[0])
    raw["input"]["base_time"] = "2026-07-20T17:00:00"
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="include a timezone"):
        load_jsonl(path)
