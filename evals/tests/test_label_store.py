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
