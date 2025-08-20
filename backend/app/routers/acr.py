import os
from datetime import datetime
from typing import Any, Dict
import importlib

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

@router.post("/internal/acr-webhook")
async def acr_webhook(request: Request) -> Dict[str, Any]:
    import main  # type: ignore

    token = request.headers.get("X-ACR-Token") or request.query_params.get("token")
    expected_token = getattr(main, "ACR_WEBHOOK_TOKEN", None)
    if not expected_token or token != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    if payload.get("action") != "push":
        return {"status": "ignored", "reason": f"action={payload.get('action')}"}

    repo = payload.get("target", {}).get("repository")
    expected_repo = os.getenv("ACR_REPOSITORY")
    if expected_repo and repo != expected_repo:
        return {"status": "ignored", "reason": f"repo={repo}"}

    kubernetes = importlib.import_module("kubernetes")
    kubernetes.config.load_incluster_config()
    api = kubernetes.client.AppsV1Api()
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": datetime.utcnow().isoformat()
                    }
                }
            }
        }
    }
    namespace = getattr(main, "K8S_NAMESPACE", "default")
    deployment = getattr(main, "K8S_DEPLOYMENT", "respondr")
    api.patch_namespaced_deployment(name=deployment, namespace=namespace, body=body)
    return {"status": "restarted", "deployment": deployment, "namespace": namespace}
