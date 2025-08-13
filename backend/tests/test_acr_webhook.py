import os
import importlib
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest
from fastapi.testclient import TestClient


class FakeAppsV1Api:
    calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def patch_namespaced_deployment(self, name: str, namespace: str, body: Dict[str, Any]):
        # Record calls for assertions
        FakeAppsV1Api.calls.append((name, namespace, body))


def fake_k8s_module():
    # Return a fake "kubernetes" module shape (client + config)
    client = SimpleNamespace(AppsV1Api=FakeAppsV1Api)

    def load_incluster_config():
        # No-op, pretend we're in cluster or configured
        return None

    def load_kube_config():
        # No-op fallback
        return None

    config = SimpleNamespace(load_incluster_config=load_incluster_config, load_kube_config=load_kube_config)
    return SimpleNamespace(client=client, config=config)


@pytest.fixture(autouse=True)
def clear_fake_calls_and_env(monkeypatch):
    # Ensure a clean slate for each test
    FakeAppsV1Api.calls.clear()

    # Ensure the expected repo for filtering
    monkeypatch.setenv("ACR_REPOSITORY", "respondr")

    # Insert our fake kubernetes module so importlib.import_module("kubernetes") finds it
    monkeypatch.setitem(os.sys.modules, "kubernetes", fake_k8s_module())

    # Prepare module-level vars expected by the handler
    import main
    main.ACR_WEBHOOK_TOKEN = "unit-test-token"
    main.K8S_NAMESPACE = "test-namespace"
    main.K8S_DEPLOYMENT = "test-deployment"

    yield


@pytest.fixture
def client():
    # Import here after fixtures set module-level variables
    import main
    return TestClient(main.app)


def test_acr_webhook_happy_path_triggers_restart(client):
    payload = {
        "action": "push",
        "target": {"repository": "respondr", "tag": "latest"},
    }
    headers = {"X-ACR-Token": "unit-test-token"}

    resp = client.post("/internal/acr-webhook", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "restarted"
    assert data["deployment"] == "test-deployment"
    assert data["namespace"] == "test-namespace"

    # Verify we patched the deployment with a restart annotation
    assert len(FakeAppsV1Api.calls) == 1
    name, namespace, body = FakeAppsV1Api.calls[0]
    assert name == "test-deployment"
    assert namespace == "test-namespace"
    annotations = body["spec"]["template"]["metadata"]["annotations"]
    assert "kubectl.kubernetes.io/restartedAt" in annotations


def test_acr_webhook_unauthorized_without_token(client):
    payload = {
        "action": "push",
        "target": {"repository": "respondr", "tag": "latest"},
    }
    # No header -> unauthorized
    resp = client.post("/internal/acr-webhook", json=payload)
    assert resp.status_code == 401
    assert len(FakeAppsV1Api.calls) == 0


def test_acr_webhook_ignored_non_push_action(client):
    payload = {
        "action": "delete",
        "target": {"repository": "respondr", "tag": "latest"},
    }
    headers = {"X-ACR-Token": "unit-test-token"}

    resp = client.post("/internal/acr-webhook", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ignored"
    assert "action=delete" in data["reason"]
    assert len(FakeAppsV1Api.calls) == 0


def test_acr_webhook_ignored_when_repo_doesnt_match(client, monkeypatch):
    # Set expected repo via env (handler reads os.getenv at runtime)
    monkeypatch.setenv("ACR_REPOSITORY", "respondr")
    payload = {
        "action": "push",
        "target": {"repository": "otherapp", "tag": "latest"},
    }
    headers = {"X-ACR-Token": "unit-test-token"}

    resp = client.post("/internal/acr-webhook", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ignored"
    assert "repo=otherapp" in data["reason"]
    assert len(FakeAppsV1Api.calls) == 0


def test_acr_webhook_accepts_token_query_param(client):
    # Same semantics as header, but via query string 'token='
    payload = {
        "action": "push",
        "target": {"repository": "respondr", "tag": "latest"},
    }
    # No header on purpose
    resp = client.post("/internal/acr-webhook?token=unit-test-token", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "restarted"
    assert len(FakeAppsV1Api.calls) == 1
