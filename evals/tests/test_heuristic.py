from datetime import datetime, timezone

from respondr_eval.schema import EvalCase, ReferenceLabel
from respondr_eval.strategies.heuristic import HeuristicStrategy


def case(text: str, base_time: str = "2026-07-21T00:00:00Z") -> EvalCase:
    return EvalCase(
        case_id="test",
        input={"text": text, "base_time": base_time, "previous_messages": []},
        reference=ReferenceLabel("Unknown", "Unknown", "Unknown"),
    )


def test_clear_response_extracts_fields_without_network():
    prediction = HeuristicStrategy().predict(
        case("Responding in SAR 078, ETA 20 minutes")
    )

    assert prediction.status == "Responding"
    assert prediction.vehicle == "SAR-78"
    assert prediction.eta_iso == "2026-07-21T00:20:00Z"
    assert prediction.input_tokens == 0
    assert prediction.output_tokens == 0


def test_stand_down_clears_eta_and_vehicle():
    prediction = HeuristicStrategy().predict(case("Copy 10-22, ETA 1830"))

    assert prediction.status == "Not Responding"
    assert prediction.vehicle == "Unknown"
    assert prediction.eta_iso == "Unknown"


def test_clock_time_uses_input_offset_and_rolls_forward():
    prediction = HeuristicStrategy().predict(
        case("Responding POV ETA 6:45 pm", "2026-07-20T18:02:00-07:00")
    )

    assert prediction.eta_iso == "2026-07-21T01:45:00Z"


def test_question_is_informational():
    prediction = HeuristicStrategy().predict(case("Where is staging?"))
    assert prediction.status == "Informational"
