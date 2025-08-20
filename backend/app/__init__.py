import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from .config import PRIMARY_HOSTNAME, LEGACY_HOSTNAMES
from .routers import webhook, responders, dashboard, acr, user

logger = logging.getLogger(__name__)

app = FastAPI()

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
