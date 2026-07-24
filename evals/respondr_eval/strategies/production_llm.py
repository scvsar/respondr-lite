"""Adapter that evaluates the production extraction pipeline with live models."""

from __future__ import annotations

import json
import importlib
import hashlib
import sys
import time
import types
from pathlib import Path
from typing import Any

from ..schema import EvalCase
from .base import Prediction, Strategy


class _RecordingCompletions:
    def __init__(self, completions: Any, deployment: str):
        self._completions = completions
        self._deployment = deployment
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs):
        request = dict(kwargs)
        request["model"] = self._deployment
        started = time.perf_counter()
        try:
            response = self._completions.create(**request)
        except Exception as exc:
            self.calls.append(
                {
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "error": type(exc).__name__,
                }
            )
            raise
        usage = getattr(response, "usage", None)
        self.calls.append(
            {
                "latency_ms": (time.perf_counter() - started) * 1000,
                "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                "response_text": str(
                    getattr(response.choices[0].message, "content", "") or ""
                ),
                "error": None,
            }
        )
        return response


class _ChatProxy:
    def __init__(self, chat: Any, deployment: str):
        self.completions = _RecordingCompletions(chat.completions, deployment)


class _ClientProxy:
    def __init__(self, client: Any, deployment: str):
        self.chat = _ChatProxy(client.chat, deployment)


def _load_prompt_variant(path: str | None) -> tuple[str | None, str | None, str]:
    if not path:
        return None, None, "production-default"
    prompt_path = Path(path)
    raw = json.loads(prompt_path.read_text(encoding="utf-8"))
    return (
        raw.get("system_prompt"),
        raw.get("user_prompt"),
        str(raw.get("name") or prompt_path.stem),
    )


def _render_prompt(template: str | None, case: EvalCase) -> str | None:
    if template is None:
        return None
    values = {
        "text": str(case.input["text"]),
        "base_time": str(case.input["base_time"]),
        "previous_eta_iso": str(case.input.get("previous_eta_iso") or "Unknown"),
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _enriched_text(case: EvalCase) -> str:
    current = str(case.input["text"])
    history = list(case.input.get("previous_messages") or [])[-5:]
    if not history:
        return current
    lines = ["Previous messages from this user:"]
    for item in history:
        lines.append(
            f"- [{item.get('timestamp', '')}] \"{item.get('text', '')}\""
            f" -> Status: {item.get('status', 'Unknown')},"
            f" Vehicle: {item.get('vehicle', 'Unknown')},"
            f" ETA: {item.get('eta', 'Unknown')}"
        )
    lines.append("")
    lines.append(f"Current message: {current}")
    return "\n".join(lines)


class ProductionLLMStrategy(Strategy):
    kind = "production_llm"

    def __init__(
        self,
        name: str,
        deployment: str,
        model_id: str,
        prompt_path: str | None = None,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        max_tokens: int | None = None,
        client: Any = None,
    ):
        if not deployment:
            raise ValueError("A live LLM experiment requires an Azure deployment name")
        self.name = name
        self.deployment = deployment
        self.model_id = model_id
        self.reasoning_effort = reasoning_effort
        self.verbosity = verbosity
        self.max_tokens = max_tokens
        self.system_prompt, self.user_prompt, self.prompt_name = _load_prompt_variant(
            prompt_path
        )
        self.prompt_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "system_prompt": self.system_prompt,
                    "user_prompt": self.user_prompt,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        repository_root = Path(__file__).resolve().parents[3]
        production_sources = [
            repository_root / "backend" / "app" / "llm.py",
            repository_root / "backend" / "app" / "utils.py",
            Path(__file__).resolve(),
        ]
        code_digest = hashlib.sha256()
        for source in production_sources:
            code_digest.update(source.read_bytes())
        self.production_code_fingerprint = code_digest.hexdigest()
        self._client = client

    @staticmethod
    def _production_module():
        repository_root = Path(__file__).resolve().parents[3]
        app_path = repository_root / "backend" / "app"
        package_name = "_respondr_eval_backend_app"
        if package_name not in sys.modules:
            package = types.ModuleType(package_name)
            package.__path__ = [str(app_path)]
            package.__package__ = package_name
            sys.modules[package_name] = package
        return importlib.import_module(f"{package_name}.llm")

    def _resolve_client(self):
        if self._client is not None:
            return self._client
        llm = self._production_module()
        if llm.client is None:
            raise RuntimeError(
                "Azure OpenAI is not configured. Set the backend Azure OpenAI environment values."
            )
        return llm.client

    def predict(self, case: EvalCase) -> Prediction:
        llm = self._production_module()
        proxy = _ClientProxy(self._resolve_client(), self.deployment)
        started = time.perf_counter()
        try:
            result = llm.extract_details_from_text(
                _enriched_text(case),
                base_time=llm.datetime.fromisoformat(
                    str(case.input["base_time"]).replace("Z", "+00:00")
                ),
                prev_eta_iso=case.input.get("previous_eta_iso"),
                sys_prompt_override=_render_prompt(self.system_prompt, case),
                user_prompt_override=_render_prompt(self.user_prompt, case),
                verbosity_override=self.verbosity,
                reasoning_effort_override=self.reasoning_effort,
                max_tokens_override=self.max_tokens,
                llm_client=proxy,
            )
            error = result.get("_llm_error")
            return Prediction(
                status=result.get("raw_status", "Unknown"),
                vehicle=result.get("vehicle", "Unknown"),
                eta_iso=result.get("eta_timestamp_utc") or "Unknown",
                confidence=result.get("status_confidence"),
                latency_ms=(time.perf_counter() - started) * 1000,
                input_tokens=sum(
                    call["input_tokens"] for call in proxy.chat.completions.calls
                ),
                output_tokens=sum(
                    call["output_tokens"] for call in proxy.chat.completions.calls
                ),
                retry_count=max(0, len(proxy.chat.completions.calls) - 1),
                error=str(error) if error else None,
                metadata={
                    "deployment": self.deployment,
                    "model_id": self.model_id,
                    "prompt": self.prompt_name,
                    "call_count": len(proxy.chat.completions.calls),
                    "raw_responses": [
                        call.get("response_text", "")
                        for call in proxy.chat.completions.calls
                        if call.get("response_text")
                    ],
                },
            ).validated()
        except Exception as exc:
            return Prediction(
                latency_ms=(time.perf_counter() - started) * 1000,
                input_tokens=sum(
                    call["input_tokens"] for call in proxy.chat.completions.calls
                ),
                output_tokens=sum(
                    call["output_tokens"] for call in proxy.chat.completions.calls
                ),
                retry_count=max(0, len(proxy.chat.completions.calls) - 1),
                error=f"{type(exc).__name__}: {exc}",
                metadata={
                    "deployment": self.deployment,
                    "model_id": self.model_id,
                    "prompt": self.prompt_name,
                },
            )

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "deployment": self.deployment,
            "model_id": self.model_id,
            "prompt": self.prompt_name,
            "prompt_fingerprint": self.prompt_fingerprint,
            "production_code_fingerprint": self.production_code_fingerprint,
            "reasoning_effort": self.reasoning_effort,
            "verbosity": self.verbosity,
            "max_tokens": self.max_tokens,
            "azure_api_version": self._production_module().azure_openai_api_version,
        }
