"""
Frontend serving routes for React SPA.
"""

import os
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import is_testing

logger = logging.getLogger(__name__)

router = APIRouter()

# Determine frontend build path
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if os.path.exists(os.path.join(backend_dir, "frontend/build")):
    frontend_build = os.path.join(backend_dir, "frontend/build")
else:
    frontend_build = os.path.join(backend_dir, "../frontend/build")

static_dir = os.path.join(frontend_build, "static")

# Mount static files if not in testing mode and directory exists
if not is_testing and os.path.exists(static_dir):
    from fastapi import FastAPI
    # Note: This will be mounted on the main app, not the router
    pass

@router.get("/")
def serve_frontend():
    """Serve the React frontend index.html."""
    if is_testing:
        return {"message": "Test mode - frontend not available"}
    
    index_path = os.path.join(frontend_build, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return {"message": "Frontend not built - run 'npm run build' in frontend directory"}

@router.get("/scvsar-logo.png")
def serve_logo():
    """Serve the SCVSAR logo."""
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    logo_path = os.path.join(frontend_build, "scvsar-logo.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path)
    raise HTTPException(status_code=404, detail="Logo not found")

@router.get("/favicon.ico")
def serve_favicon():
    """Serve the favicon."""
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "favicon.ico")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")

@router.get("/manifest.json")
def serve_manifest():
    """Serve the web app manifest."""
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "manifest.json")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")

@router.get("/robots.txt")
def serve_robots():
    """Serve robots.txt."""
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "robots.txt")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")

@router.get("/logo192.png")
def serve_logo192():
    """Serve the 192px logo."""
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "logo192.png")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")

@router.get("/logo512.png")
def serve_logo512():
    """Serve the 512px logo."""
    if is_testing:
        raise HTTPException(status_code=404, detail="Not available in tests")
    p = os.path.join(frontend_build, "logo512.png")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Not found")

# SPA catch-all for client routes; must be declared last in the main app
def add_spa_catch_all(app):
    """Add SPA catch-all route to the main app (must be added last)."""
    @app.get("/{full_path:path}")
    def spa_catch_all(full_path: str):
        """Catch-all route for SPA client-side routing."""
        if is_testing:
            raise HTTPException(status_code=404, detail="Not available in tests")
        index_path = os.path.join(frontend_build, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Frontend not built")
    
    return spa_catch_all

# Function to mount static files (called from main app)
def mount_static_files(app):
    """Mount static files directory."""
    if not is_testing and os.path.exists(static_dir):
        try:
            app.mount("/static", StaticFiles(directory=static_dir), name="static")
            logger.info(f"Mounted static files from {static_dir}")
        except Exception as e:
            logger.warning(f"Failed to mount static files: {e}")