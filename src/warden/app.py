from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .api import mcharness_router
from .branding import CATEGORY, PRODUCT_NAME, PUBLIC_URL, REPO_NAME, TAGLINE

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
    app.add_middleware(NoCacheWebAssetsMiddleware)

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
