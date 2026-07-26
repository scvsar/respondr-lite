import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from respondr_eval.schema import EvalCase, ReferenceLabel
from respondr_eval.strategies.production_llm import ProductionLLMStrategy


ROOT = Path(__file__).parents[1]


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


def test_prompt_variant_renders_utc_and_local_reference_times(tmp_path):
    prompt_path = tmp_path / "prompt.json"
    prompt_path.write_text(
        json.dumps(
            {
                "name": "render-test",
                "system_prompt": "Extract facts.",
                "user_prompt": (
                    "UTC {{base_time}}\n"
                    "Local {{base_time_local}}\n"
                    "Zone {{timezone}}\n"
                    "ETA {{previous_eta_iso}}\n"
                    "Text {{text}}"
                ),
            }
        ),
        encoding="utf-8",
    )
    fake = FakeClient()
    strategy = ProductionLLMStrategy(
        name="candidate",
        deployment="candidate-deployment",
        model_id="candidate-model",
        prompt_path=str(prompt_path),
        client=fake,
    )
    case = EvalCase(
        case_id="synthetic",
        input={
            "text": "Responding POV",
            "base_time": "2026-08-10T00:00:00Z",
            "timezone": "America/Los_Angeles",
            "previous_eta_iso": "2026-08-10T01:00:00Z",
            "previous_messages": [],
        },
        reference=ReferenceLabel(
            "Responding", "POV", "2026-08-10T01:00:00Z"
        ),
        annotation={"state": "approved"},
        split="test",
    )

    llm = strategy._production_module()
    with patch.object(llm, "azure_openai_deployment", "configured-deployment"):
        strategy.predict(case)

    user_prompt = fake.chat.completions.requests[0]["messages"][1]["content"]
    assert "UTC 2026-08-10T00:00:00Z" in user_prompt
    assert "Local 2026-08-09T17:00:00-07:00" in user_prompt
    assert "Zone America/Los_Angeles" in user_prompt
    assert "ETA 2026-08-10T01:00:00Z" in user_prompt


def test_contrastive_prompt_has_synthetic_correct_and_incorrect_examples():
    prompt = json.loads(
        (ROOT / "prompts" / "sar-extraction-contrastive-v1.json").read_text(
            encoding="utf-8"
        )
    )
    system_prompt = prompt["system_prompt"]

    assert prompt["example_count"] == 16
    assert system_prompt.count("\nExample ") == 16
    assert system_prompt.count("\nIncorrect:") == 16
    assert system_prompt.count("\nCorrect:") == 16
    assert "The following examples are synthetic." in system_prompt


def test_ste_prompt_preserves_the_production_schema_without_examples():
    prompt = json.loads(
        (ROOT / "prompts" / "production-ste-v1.json").read_text(encoding="utf-8")
    )

    assert prompt["example_count"] == 0
    assert "{{timezone}}" in prompt["system_prompt"]
    assert "\"vehicle\"" in prompt["system_prompt"]
    assert "\"eta_iso\"" in prompt["system_prompt"]
    assert "\"status\"" in prompt["system_prompt"]
