from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .api import captain_watcher_background_loop, dropzone_watcher_background_loop, mcharness_router
from .branding import CATEGORY, PRODUCT_NAME, PUBLIC_URL, REPO_NAME, TAGLINE
from .brain.graph_api import router as brain_graph_router

_ROOT = Path(__file__).resolve().parents[2]
_WEB_DIR = _ROOT / "web"


class NoCacheWebAssetsMiddleware(BaseHTTPMiddleware):
    """Force browsers to revalidate /web/*.{css,js,html} on every load.

    Local-first dev loop: without this, a plain refresh can keep serving a
    stale cached copy of the UI even after the file on disk has changed.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/web/") and path.endswith((".css", ".js", ".html")):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title=PRODUCT_NAME,
        version="0.1.0",
        description=TAGLINE,
    )
    app.state.branding = {
        "product_name": PRODUCT_NAME,
        "repo_name": REPO_NAME,
        "public_url": PUBLIC_URL,
        "tagline": TAGLINE,
        "category": CATEGORY,
    }
    app.include_router(mcharness_router)
    app.include_router(brain_graph_router)
    app.add_middleware(NoCacheWebAssetsMiddleware)

    @app.get("/", include_in_schema=False)
    def root_redirect():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/web/warden/app.html")

    @app.on_event("startup")
    async def start_captain_watcher_loop():
        app.state.captain_watcher_task = asyncio.create_task(captain_watcher_background_loop())

    @app.on_event("shutdown")
    async def stop_captain_watcher_loop():
        task = getattr(app.state, "captain_watcher_task", None)
        if task is not None:
            task.cancel()

    @app.on_event("startup")
    async def start_dropzone_watcher_loop():
        app.state.dropzone_watcher_task = asyncio.create_task(dropzone_watcher_background_loop())

    @app.on_event("shutdown")
    async def stop_dropzone_watcher_loop():
        task = getattr(app.state, "dropzone_watcher_task", None)
        if task is not None:
            task.cancel()

    # Marius Core Integration
    try:
        from src.marius.api import router as marius_router
        from src.marius.bot import start_bot
        app.include_router(marius_router)

        @app.on_event("startup")
        def startup_marius():
            start_bot()
    except ImportError as e:
        # Fallback if Marius is not fully implemented or has missing deps
        print(f"Marius integration skipped: {e}")

    if _WEB_DIR.exists():
        app.mount("/web", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
    return app


app = create_app()
