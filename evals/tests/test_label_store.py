from pathlib import Path

from fastapi.testclient import TestClient

from respondr_eval.dataset import load_jsonl, write_jsonl
from respondr_eval.label_store import LabelStore
from respondr_eval.labeling_app import create_app


SEED = Path(__file__).parents[1] / "data" / "synthetic_seed.jsonl"


def _proposed_dataset(tmp_path):
    cases = load_jsonl(SEED)[:3]
    for case in cases:
        case.annotation["state"] = "proposed"
        case.split = "unassigned"
    path = tmp_path / "labels.jsonl"
    write_jsonl(path, cases)
    return path


def test_store_marks_changed_approval_as_corrected(tmp_path):
    path = _proposed_dataset(tmp_path)
    store = LabelStore(path)
    first = store.list_cases()[0]

    updated = store.update(
        first.case_id,
        {"status": "Unknown", "vehicle": "Unknown", "eta_iso": "Unknown"},
        state="approved",
        reviewer="rt",
    )

    assert updated.annotation["state"] == "corrected"
    assert updated.annotation["reviewer"] == "rt"
    assert load_jsonl(path)[0].case_id


def test_labeling_api_returns_and_updates_cases(tmp_path):
    path = _proposed_dataset(tmp_path)
    client = TestClient(create_app(path))

    queue = client.get("/api/cases").json()
    assert queue["total"] == 3
    case = queue["case"]
    response = client.put(
        f"/api/cases/{case['case_id']}",
        json={
            "reference": case["reference"],
            "state": "approved",
            "reviewer": "rt",
        },
    )

    assert response.status_code == 200
    assert response.json()["summary"]["reviewed"] == 1


def test_results_api_lists_and_returns_private_reports(tmp_path):
    path = _proposed_dataset(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    report = {
        "schema_version": "1.0",
        "created_at": "2026-07-23T23:57:59Z",
        "dataset": {
            "fingerprint": "synthetic-fingerprint",
            "kind": "synthetic",
            "evaluation_split": "dev",
            "evaluation_case_count": 3,
        },
        "experiments": [
            {
                "name": "heuristic-v1",
                "meets_target": True,
                "metrics": {"exact_match_accuracy": 1.0},
                "case_results": [],
            }
        ],
        "paired_comparisons": [],
        "least_expensive_meeting_target": "heuristic-v1",
    }
    report_path = results / "run-20260723T235759Z.json"
    report_path.write_text(__import__("json").dumps(report), encoding="utf-8")
    client = TestClient(create_app(path, results_dir=results))

    page = client.get("/results")
    listing = client.get("/api/results")
    detail = client.get(f"/api/results/{report_path.name}")
    traversal = client.get("/api/results/not-a-run.json")

    assert page.status_code == 200
    assert "benchmark results" in page.text
    assert "Technical JSON" in page.text
    assert "Run setup" in page.text
    assert listing.json()["runs"][0]["file"] == report_path.name
    assert listing.json()["runs"][0]["dataset_kind"] == "synthetic"
    assert detail.json()["least_expensive_meeting_target"] == "heuristic-v1"
    assert traversal.status_code == 404
