"""Provider calls must honor retry limits and protect message content."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
from openai import APIStatusError
import pytest

from app import llm


def provider_error(status, body=None):
    response = httpx.Response(status, request=httpx.Request('POST', 'https://example.test'))
    return APIStatusError('synthetic-private-provider-details', response=response, body=body)


def response(content='{"vehicle":"Unknown","status":"Responding","eta_iso":"Unknown","confidence":0.8}', reason='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=reason)], usage=None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(llm, 'ENABLE_LLM_MOCK', False)
    monkeypatch.setattr(llm, 'azure_openai_deployment', 'gpt-6-luna')
    monkeypatch.setattr(llm, 'LLM_MAX_RETRIES', 3)
    return MagicMock()


def call(client):
    return llm._call_llm_only('Synthetic response', datetime(2026, 1, 1, tzinfo=timezone.utc), None, client)


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_permanent_failure_is_not_retried(client, status, caplog):
    client.chat.completions.create.side_effect = provider_error(status)
    result = call(client)
    assert '_llm_error' in result
    assert client.chat.completions.create.call_count == 1
    assert 'synthetic-private-provider-details' not in caplog.text
    assert 'synthetic-private-provider-details' not in str(result)


def test_transient_failure_honors_total_attempt_limit(client, monkeypatch):
    monkeypatch.setattr('time.sleep', lambda _: None)
    client.chat.completions.create.side_effect = provider_error(503)
    assert '_llm_error' in call(client)
    assert client.chat.completions.create.call_count == 3


def test_transient_failure_can_recover(client, monkeypatch):
    monkeypatch.setattr('time.sleep', lambda _: None)
    client.chat.completions.create.side_effect = [provider_error(429), response()]
    assert call(client)['status'] == 'Responding'
    assert client.chat.completions.create.call_count == 2


def test_output_exhaustion_increases_tokens_within_total_limit(client, monkeypatch):
    monkeypatch.setattr('time.sleep', lambda _: None)
    client.chat.completions.create.side_effect = [response('', 'length'), response()]
    assert call(client)['status'] == 'Responding'
    calls = client.chat.completions.create.call_args_list
    assert calls[1].kwargs['max_completion_tokens'] > calls[0].kwargs['max_completion_tokens']
    assert calls[1].kwargs['max_completion_tokens'] <= llm.MAX_COMPLETION_TOKENS_CAP


def test_explicit_unsupported_parameter_is_removed_on_next_attempt(client, monkeypatch):
    monkeypatch.setattr(llm, '_select_kwargs_for_model', lambda _: {'verbosity': 'low', 'max_completion_tokens': 1024})
    client.chat.completions.create.side_effect = [
        provider_error(400, {'error': {'code': 'unsupported_parameter', 'param': 'verbosity'}}), response(),
    ]
    assert call(client)['status'] == 'Responding'
    assert 'verbosity' not in client.chat.completions.create.call_args_list[1].kwargs


def test_empty_responses_cannot_start_additional_fallback_loops(client, monkeypatch):
    monkeypatch.setattr('time.sleep', lambda _: None)
    client.chat.completions.create.return_value = response('')
    assert '_llm_error' in call(client)
    assert client.chat.completions.create.call_count == 3


def test_truncated_content_cannot_be_used_as_a_complete_result(client, monkeypatch):
    monkeypatch.setattr('time.sleep', lambda _: None)
    client.chat.completions.create.return_value = response('{"vehicle":"POV"}', 'length')
    assert call(client) == {'_llm_error': 'output_limit'}
    assert client.chat.completions.create.call_count == 3


@pytest.mark.parametrize('reason,refusal', [('content_filter', None), ('stop', 'Synthetic refusal')])
def test_filtered_or_refused_output_is_not_retried(client, reason, refusal):
    filtered = response('', reason)
    filtered.choices[0].message.refusal = refusal
    client.chat.completions.create.return_value = filtered
    assert call(client) == {'_llm_error': 'content_filtered'}
    assert client.chat.completions.create.call_count == 1


def test_connection_failure_can_recover(client, monkeypatch):
    from openai import APIConnectionError
    monkeypatch.setattr('time.sleep', lambda _: None)
    client.chat.completions.create.side_effect = [
        APIConnectionError(request=httpx.Request('POST', 'https://example.test')), response(),
    ]
    assert call(client)['status'] == 'Responding'
    assert client.chat.completions.create.call_count == 2
