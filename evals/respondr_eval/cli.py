"""Command-line interface for datasets, labeling, and experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset import assign_grouped_splits, load_jsonl, summarize, write_jsonl
from .labeling_app import serve
from .runner import run
from .sampling import sample_production


def _default_local_dataset() -> str:
    return str(Path(__file__).resolve().parents[1] / "local" / "prod-ground-truth.jsonl")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="respondr-eval",
        description="Evaluate Respondr extraction strategies.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="Validate and summarize a dataset.")
    validate.add_argument("dataset")

    split = commands.add_parser(
        "split", help="Assign reviewed cases to mission-grouped splits."
    )
    split.add_argument("dataset")
    split.add_argument("--seed", type=int, default=20260723)

    sample = commands.add_parser(
        "sample-prod", help="Read production messages into an ignored local dataset."
    )
    sample.add_argument(
        "--account", default="respondrlitesg5e55325b", help="Azure storage account."
    )
    sample.add_argument("--table", default="ResponderMessages")
    sample.add_argument("--output", default=_default_local_dataset())
    sample.add_argument(
        "--max-cases", type=int, default=0, help="Use 0 to keep all active messages."
    )

    label = commands.add_parser("label", help="Start the localhost annotation interface.")
    label.add_argument("--dataset", default=_default_local_dataset())
    label.add_argument("--port", type=int, default=8765)
    label.add_argument("--no-browser", action="store_true")

    evaluate = commands.add_parser("run", help="Run an experiment matrix.")
    evaluate.add_argument("config")
    evaluate.add_argument("--allow-live-llm", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        cases = load_jsonl(args.dataset)
        print(json.dumps(summarize(cases), indent=2, sort_keys=True))
        return 0
    if args.command == "split":
        cases = load_jsonl(args.dataset)
        assign_grouped_splits(cases, seed=args.seed)
        write_jsonl(args.dataset, cases)
        print(json.dumps(summarize(cases), indent=2, sort_keys=True))
        return 0
    if args.command == "sample-prod":
        result = sample_production(
            account_name=args.account,
            table_name=args.table,
            output_path=args.output,
            max_cases=args.max_cases,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "label":
        serve(
            args.dataset,
            port=args.port,
            open_browser=not args.no_browser,
        )
        return 0
    if args.command == "run":
        json_path, markdown_path = run(
            args.config, allow_live_llm=args.allow_live_llm
        )
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {markdown_path}")
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")
