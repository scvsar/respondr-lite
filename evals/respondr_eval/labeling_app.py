"""Localhost-only human annotation interface."""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Any

from .label_store import LabelStore


def create_app(dataset_path: str | Path):
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

    @app.get("/", response_class=HTMLResponse)
    def index():
        return index_path.read_text(encoding="utf-8")

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

    return app


def serve(
    dataset_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
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
    uvicorn.run(create_app(dataset_path), host=host, port=port, log_level="warning")
