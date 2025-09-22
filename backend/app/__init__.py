import os
import logging
import asyncio
from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi

from .routers import webhook, responders, dashboard, user, frontend, auth
from .queue_listener import listen_to_queue
from .retention_scheduler import retention_cleanup_task
from .request_logger import log_request

logger = logging.getLogger(__name__)

# Disable automatic docs generation - we'll create protected versions
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Enable CORS for local dev (CRA on :3100) and Static Web Apps
_allow_dev_cors = True  # safe default for local runs; can tighten with env if needed
if _allow_dev_cors:
    origins = [
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ]
    
    # Add Static Web App origins from environment variable if present
    static_web_app_url = os.getenv("STATIC_WEB_APP_URL")
    if static_web_app_url:
        origins.append(static_web_app_url)
        # Also add the default Azure Static Web Apps domain pattern
        origins.append("https://*.azurestaticapps.net")
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log HTTP requests for debugging, especially wake probes."""
    
    # Determine if this is a wake-related request
    path = str(request.url.path)
    is_wake = "/wake" in path or path == "/"
    is_storage_info = "/storage-info" in path
    is_health = "/health" in path or "/ready" in path
    
    # Tag the request appropriately
    if is_wake:
        tag = "WAKE_REQUEST"
    elif is_storage_info:
        tag = "STORAGE_INFO_PROBE"
    elif is_health:
        tag = "HEALTH_CHECK"
    elif path.startswith("/api/"):
        tag = "API_REQUEST"
    else:
        tag = "OTHER_REQUEST"
    
    # Process the request
    response = await call_next(request)
    
    # Log interesting requests (not static files)
    if not path.startswith("/static/") and not path.endswith((".js", ".css", ".png", ".ico", ".map")):
        # Check if request logging is enabled
        enable_logging = os.getenv("ENABLE_REQUEST_LOGGING", "false").lower() == "true"
        if enable_logging:
            try:
                await log_request(request, response, tag)
            except Exception as e:
                logger.error(f"Failed to log request {path}: {e}")
    
    return response


app.include_router(webhook.router)
app.include_router(responders.router)
app.include_router(dashboard.router)
app.include_router(user.router)
app.include_router(auth.router)
app.include_router(frontend.router)

# Mount static files for frontend
frontend.mount_static_files(app)

# Protected documentation endpoints
from .routers.responders import require_authenticated_access

@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(_: bool = Depends(require_authenticated_access)):
    """Protected OpenAPI schema endpoint."""
    return get_openapi(title="Respondr API", version="1.0.0", routes=app.routes)

@app.get("/docs", include_in_schema=False)
async def get_swagger_ui(_: bool = Depends(require_authenticated_access)):
    """Protected Swagger UI documentation."""
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Respondr API Docs")

@app.get("/redoc", include_in_schema=False)
async def get_redoc(_: bool = Depends(require_authenticated_access)):
    """Protected ReDoc documentation."""
    return get_redoc_html(openapi_url="/openapi.json", title="Respondr API Docs")

# Add SPA catch-all route (must be last)
frontend.add_spa_catch_all(app)


@app.on_event("startup")
async def _start_queue_listener() -> None:
    """Launch background task to process queue messages."""
    asyncio.create_task(listen_to_queue())


@app.on_event("startup")
async def _start_retention_cleanup() -> None:
    """Launch background task for retention cleanup."""
    asyncio.create_task(retention_cleanup_task())
