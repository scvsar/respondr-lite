<<<<<<< HEAD
"""Respondr Backend - Modular FastAPI Application.

A Search and Rescue (SAR) response tracking system with:
- GroupMe webhook integration
- LLM-powered message parsing
- Real-time responder dashboards
- Admin management interface
"""

import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.routers import webhook, responders, dashboard, acr, user
from app.config import is_testing

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Respondr Backend",
    description="SAR Response Tracking System",
    version="2.0.0"
)

# Include routers
app.include_router(user.router, tags=["Authentication"])
app.include_router(webhook.router, tags=["Webhooks"])
app.include_router(responders.router, tags=["Responders"])
app.include_router(dashboard.router, tags=["Dashboard"])
app.include_router(acr.router, tags=["Admin"])

# Mount static files (only in production)
if not is_testing:
    static_dir = Path("static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory="static"), name="static")

# Health check
@app.get("/health")
def health_check():
    """Health check endpoint for k8s probes."""
    return {"status": "healthy"}

# Make extract_details_from_text and client available for tests
from app.llm import extract_details_from_text
from app import llm as llm_module
from app.config import ACR_WEBHOOK_TOKEN as _acr_token, K8S_NAMESPACE as _k8s_namespace, K8S_DEPLOYMENT as _k8s_deployment

# Compatibility for existing tests
messages = []  # Placeholder for tests
client = llm_module.client  # Expose client for test patching
ACR_WEBHOOK_TOKEN = _acr_token  # Expose for test modification
K8S_NAMESPACE = _k8s_namespace  # Expose for test modification  
K8S_DEPLOYMENT = _k8s_deployment  # Expose for test modification


def load_messages():
    """Load messages from storage (placeholder for tests)."""
    global messages
    messages = []


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
=======
"""Entry point for Respondr backend (refactored)."""
from app import app  # type: ignore  # FastAPI instance
from app.llm import extract_details_from_text, client
from app.storage import load_messages, save_messages
from typing import Any, Dict, List

# In-memory message store
messages: List[Dict[str, Any]] = []
load_messages()

# Variables used by internal ACR webhook tests
ACR_WEBHOOK_TOKEN = None
K8S_NAMESPACE = "default"
K8S_DEPLOYMENT = "respondr"

__all__ = [
    "app",
    "extract_details_from_text",
    "client",
    "messages",
    "load_messages",
    "save_messages",
    "ACR_WEBHOOK_TOKEN",
    "K8S_NAMESPACE",
    "K8S_DEPLOYMENT",
]
>>>>>>> ef84adee5db2588b7c1441dfc10679fb2b09f3e0
