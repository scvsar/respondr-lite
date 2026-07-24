"""Localhost-only human annotation interface."""

from __future__ import annotations

import json
import threading
import webbrowser
from pathlib import Path
from typing import Any

from .label_store import LabelStore


def create_app(
    dataset_path: str | Path,
    results_dir: str | Path | None = None,
):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse
    except ImportError as exc:
        raise RuntimeError(
            "The labeler requires: pip install -e 'evals[labeling]'"
        ) from exc

    store = LabelStore(dataset_path)
    app = FastAPI(title="Respondr Ground Truth Labeler")
    index_path = Path(__file__).with_name("labeling.html")
    results_path = Path(__file__).with_name("results.html")
    report_directory = (
        Path(results_dir).resolve()
        if results_dir
        else Path(__file__).resolve().parents[1] / "results"
    )

    @app.get("/", response_class=HTMLResponse)
    def index():
        return index_path.read_text(encoding="utf-8")

    @app.get("/results", response_class=HTMLResponse)
    def results():
        return results_path.read_text(encoding="utf-8")

    @app.get("/api/summary")
    def summary():
        return store.summary()

    @app.get("/api/cases")
    def cases(state: str = "proposed", offset: int = 0):
        items = store.list_cases(state)
        if not items:
            return {"total": 0, "offset": 0, "case": None}
        safe_offset = max(0, min(offset, len(items) - 1))
        return {
            "total": len(items),
            "offset": safe_offset,
            "case": items[safe_offset].to_dict(),
        }

    @app.put("/api/cases/{case_id}")
    def update_case(case_id: str, payload: dict[str, Any]):
        try:
            case = store.update(
                case_id,
                reference=dict(payload.get("reference") or {}),
                state=str(payload.get("state") or "approved"),
                notes=str(payload.get("notes") or ""),
                reviewer=str(payload.get("reviewer") or ""),
            )
            return {"case": case.to_dict(), "summary": store.summary()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/split")
    def split(payload: dict[str, Any] | None = None):
        seed = int((payload or {}).get("seed", 20260723))
        return store.split(seed)

    @app.get("/api/results")
    def list_results():
        runs = []
        if report_directory.exists():
            for path in sorted(
                report_directory.glob("run-*.json"),
                reverse=True,
            ):
                try:
                    report = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                dataset = dict(report.get("dataset") or {})
                runs.append(
                    {
                        "file": path.name,
                        "created_at": report.get("created_at"),
                        "dataset_fingerprint": dataset.get("fingerprint"),
                        "evaluation_split": dataset.get("evaluation_split"),
                        "evaluation_case_count": dataset.get(
                            "evaluation_case_count", 0
                        ),
                        "experiment_count": len(report.get("experiments") or []),
                        "selected": report.get(
                            "least_expensive_meeting_target"
                        ),
                    }
                )
        return {"runs": runs}

    @app.get("/api/results/{report_file}")
    def get_result(report_file: str):
        if (
            Path(report_file).name != report_file
            or not report_file.startswith("run-")
            or not report_file.endswith(".json")
        ):
            raise HTTPException(status_code=404, detail="Report not found")
        path = report_directory / report_file
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Report not found")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="Report is invalid") from exc

    return app


def serve(
    dataset_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    results_dir: str | Path | None = None,
) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The private labeling interface can bind only to localhost")
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "The labeler requires: pip install -e 'evals[labeling]'"
        ) from exc
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(
        create_app(dataset_path, results_dir=results_dir),
        host=host,
        port=port,
        log_level="warning",
    )
