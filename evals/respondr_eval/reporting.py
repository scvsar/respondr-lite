"""Machine-readable and concise Markdown experiment reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_report(output_dir: str | Path, run: dict[str, Any]) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = directory / f"run-{stamp}.json"
    markdown_path = directory / f"run-{stamp}.md"
    json_path.write_text(
        json.dumps(run, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(run), encoding="utf-8")
    return json_path, markdown_path


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"


def _number(value: Any, digits: int = 2) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def _case_count_label(dataset_kind: str) -> str:
    if dataset_kind == "assumed-production":
        return "Assumed-label evaluation cases"
    if dataset_kind == "synthetic":
        return "Synthetic evaluation cases"
    return "Reviewed evaluation cases"


def _markdown(run: dict[str, Any]) -> str:
    dataset_kind = run["dataset"].get("kind", "unknown")
    lines = [
        "# Respondr evaluation report",
        "",
        f"- Dataset type: `{dataset_kind}`",
        f"- Dataset fingerprint: `{run['dataset']['fingerprint']}`",
        f"- Evaluation split: `{run['dataset']['evaluation_split']}`",
        f"- {_case_count_label(dataset_kind)}: {run['dataset']['evaluation_case_count']}",
        f"- ETA tolerance: {run['eta_tolerance_minutes']} minutes",
        "",
        "## Results",
        "",
        "| Experiment | Target | Status F1 | Vehicle | ETA | Exact | p95 ms | Cost/1k |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in run["experiments"]:
        metrics = result["metrics"]
        lines.append(
            "| {name} | {target} | {status} | {vehicle} | {eta} | {exact} | {p95} | {cost} |".format(
                name=result["name"],
                target="pass" if result["meets_target"] else "fail",
                status=_pct(metrics["status_macro_f1"]),
                vehicle=_pct(metrics["vehicle_accuracy"]),
                eta=_pct(metrics["eta_accuracy"]),
                exact=_pct(metrics["exact_match_accuracy"]),
                p95=_number(metrics["latency_p95_ms"], 1),
                cost=_number(metrics["cost_per_1000_messages_usd"], 4),
            )
        )

    lines.extend(["", "## Selection", ""])
    selected = run.get("least_expensive_meeting_target")
    if selected:
        lines.append(
            f"`{selected}` is the least expensive evaluated strategy that meets all targets."
        )
    else:
        lines.append("No evaluated strategy meets all targets.")

    if run.get("paired_comparisons"):
        lines.extend(["", "## Paired comparisons", ""])
        for comparison in run["paired_comparisons"]:
            value = comparison["comparison"]
            delta = value.get("exact_match_delta")
            lines.append(
                f"- `{comparison['candidate']}` versus `{comparison['baseline']}`:"
                f" exact-match delta {_pct(delta)};"
                f" {value.get('wins', 0)} wins,"
                f" {value.get('ties', 0)} ties,"
                f" {value.get('losses', 0)} losses."
            )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- The report does not contain raw responder messages.",
            "- Live-model results depend on the recorded deployment, prompt, and pricing configuration.",
            "- Use the held-out test split only for final selection.",
            "",
        ]
    )
    return "\n".join(lines)
