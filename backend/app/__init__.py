import os
import logging
import asyncio
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .routers import webhook, responders, dashboard, user, frontend, auth
from .queue_listener import listen_to_queue
from .retention_scheduler import retention_cleanup_task
from .request_logger import log_request

logger = logging.getLogger(__name__)

app = FastAPI()

# Enable CORS for local dev (CRA on :3100)
_allow_dev_cors = True  # safe default for local runs; can tighten with env if needed
if _allow_dev_cors:
    origins = [
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ]
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
