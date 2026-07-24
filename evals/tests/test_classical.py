from pathlib import Path

from respondr_eval.dataset import load_jsonl
from respondr_eval.strategies.classical import ClassicalStrategy


SEED = Path(__file__).parents[1] / "data" / "synthetic_seed.jsonl"


def test_classical_strategy_trains_and_sweeps():
    cases = load_jsonl(SEED, reviewed_only=True)
    train = [case for case in cases if case.split == "train"]
    dev = [case for case in cases if case.split == "dev"]
    test = [case for case in cases if case.split == "test"]
    strategy = ClassicalStrategy(tune=True)

    strategy.fit(train, dev)
    prediction = strategy.predict(test[0])

    assert prediction.status in {
        "Responding",
        "Available",
        "Informational",
        "Cancelled",
        "Not Responding",
        "Unknown",
    }
    assert prediction.vehicle == "SAR-45"
    assert len(strategy.sweep_results) == 24
