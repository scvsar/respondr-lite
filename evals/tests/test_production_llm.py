from types import SimpleNamespace
from unittest.mock import patch

from respondr_eval.schema import EvalCase, ReferenceLabel
from respondr_eval.strategies.production_llm import ProductionLLMStrategy


class FakeCompletions:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            '{"status":"Responding","vehicle":"POV",'
                            '"eta_iso":"2026-07-24T01:00:00Z",'
                            '"confidence":0.95,"evidence":"responding"}'
                        )
                    )
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
            ),
        )


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


def test_adapter_uses_production_pipeline_and_records_cost_inputs():
    fake = FakeClient()
    strategy = ProductionLLMStrategy(
        name="candidate",
        deployment="candidate-deployment",
        model_id="candidate-model",
        client=fake,
    )
    case = EvalCase(
        case_id="synthetic",
        input={
            "text": "Responding POV ETA 1800",
            "base_time": "2026-07-24T00:00:00Z",
            "previous_messages": [],
        },
        reference=ReferenceLabel(
            "Responding", "POV", "2026-07-24T01:00:00Z"
        ),
        annotation={"state": "approved"},
        split="test",
    )

    llm = strategy._production_module()
    with patch.object(llm, "azure_openai_deployment", "configured-deployment"):
        prediction = strategy.predict(case)

    assert fake.chat.completions.requests[0]["model"] == "candidate-deployment"
    assert prediction.status == "Responding"
    assert prediction.input_tokens == 100
    assert prediction.output_tokens == 20
    assert prediction.metadata["model_id"] == "candidate-model"
