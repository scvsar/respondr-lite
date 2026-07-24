"""Atomic local annotation storage."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from .dataset import assign_grouped_splits, load_jsonl, summarize, write_jsonl
from .schema import ANNOTATION_STATES, EvalCase, ReferenceLabel


class LabelStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._lock = Lock()
        self._cases = load_jsonl(self.path)
        self._by_id = {case.case_id: case for case in self._cases}

    def summary(self) -> dict[str, object]:
        with self._lock:
            return summarize(self._cases)

    def list_cases(self, state: str = "proposed") -> list[EvalCase]:
        with self._lock:
            if state == "all":
                items = list(self._cases)
            elif state == "reviewed":
                items = [case for case in self._cases if case.is_reviewed]
            else:
                items = [
                    case
                    for case in self._cases
                    if case.annotation.get("state") == state
                ]
            return sorted(
                items,
                key=lambda case: (
                    -int(case.annotation.get("review_priority", 0)),
                    case.input["base_time"],
                    case.case_id,
                ),
            )

    def get(self, case_id: str) -> EvalCase:
        with self._lock:
            try:
                return self._by_id[case_id]
            except KeyError as exc:
                raise KeyError(f"Unknown case_id: {case_id}") from exc

    def update(
        self,
        case_id: str,
        reference: dict[str, Any],
        state: str,
        notes: str = "",
        reviewer: str = "",
    ) -> EvalCase:
        if state not in ANNOTATION_STATES:
            raise ValueError(f"Unsupported annotation state: {state}")
        label = ReferenceLabel.from_dict(reference)
        with self._lock:
            case = self._by_id.get(case_id)
            if case is None:
                raise KeyError(f"Unknown case_id: {case_id}")
            changed = label != case.reference
            case.reference = label
            case.annotation.update(
                {
                    "state": "corrected" if state == "approved" and changed else state,
                    "notes": str(notes or ""),
                    "reviewer": str(reviewer or ""),
                }
            )
            write_jsonl(self.path, self._cases)
            return case

    def split(self, seed: int = 20260723) -> dict[str, object]:
        with self._lock:
            assign_grouped_splits(self._cases, seed=seed)
            write_jsonl(self.path, self._cases)
            return summarize(self._cases)
