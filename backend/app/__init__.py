import os
import logging
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from .config import PRIMARY_HOSTNAME, LEGACY_HOSTNAMES
from .routers import webhook, responders, dashboard, acr, user, frontend
from .queue_listener import listen_to_queue

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
async def hostname_redirect_middleware(request: Request, call_next):
    """Redirect legacy hostnames to primary hostname with 301 permanent redirect."""
    host = request.headers.get("host", "").lower()
    
    # Remove port if present for comparison
    host_without_port = host.split(":")[0]
    
    if host_without_port in LEGACY_HOSTNAMES:
        # Construct the new URL with the primary hostname
        scheme = "https"  # Always redirect to HTTPS
        new_url = f"{scheme}://{PRIMARY_HOSTNAME}{request.url.path}"
        if request.url.query:
            new_url += f"?{request.url.query}"
        
        logger.info(f"Redirecting {host} -> {PRIMARY_HOSTNAME}: {request.url} -> {new_url}")
        return RedirectResponse(url=new_url, status_code=301)
    
    # Not a legacy hostname, continue with normal processing
    response = await call_next(request)
    return response

app.include_router(webhook.router)
app.include_router(responders.router)
app.include_router(dashboard.router)
app.include_router(acr.router)
app.include_router(user.router)
app.include_router(frontend.router)

# Mount static files for frontend
frontend.mount_static_files(app)

# Add SPA catch-all route (must be last)
frontend.add_spa_catch_all(app)


@app.on_event("startup")
async def _start_queue_listener() -> None:
    """Launch background task to process queue messages."""
    asyncio.create_task(listen_to_queue())
