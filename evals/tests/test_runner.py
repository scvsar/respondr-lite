import json
from pathlib import Path

from respondr_eval.runner import run


ROOT = Path(__file__).parents[1]


def test_example_matrix_writes_private_reports(tmp_path):
    config = json.loads(
        (ROOT / "configs" / "example_experiments.json").read_text(encoding="utf-8")
    )
    config["dataset"] = str(ROOT / "data" / "synthetic_seed.jsonl")
    config["pricing"] = str(ROOT / "configs" / "pricing.example.json")
    config["output_dir"] = str(tmp_path / "results")
    config["cache"] = str(tmp_path / "cache.jsonl")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    json_path, markdown_path = run(path)

    result = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(result["experiments"]) == 2
    assert result["dataset"]["evaluation_case_count"] == 6
    assert result["environment"]["git_commit"]
    assert "raw responder" in markdown_path.read_text(encoding="utf-8")
    assert "Rolling in 45" not in json_path.read_text(encoding="utf-8")
