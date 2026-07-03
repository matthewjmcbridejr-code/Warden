"""Embedding abstraction over Ollama. Returns None on any failure so callers fall back to keyword search."""
from __future__ import annotations

import os
import logging
from typing import Optional

log = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.getenv("WARDEN_EMBED_MODEL", "mxbai-embed-large")


def get_embedding(text: str) -> Optional[list[float]]:
    """Return embedding vector or None if Ollama is unavailable."""
    try:
        import httpx
        payload = {"model": EMBED_MODEL, "prompt": text[:8000]}
        resp = httpx.post(f"{OLLAMA_URL}/api/embeddings", json=payload, timeout=15.0)
        resp.raise_for_status()
        return resp.json().get("embedding")
    except Exception as exc:
        log.debug("Ollama embedding unavailable (%s): %s", type(exc).__name__, exc)
        return None


def is_available() -> bool:
    """Quick liveness check — does not embed anything."""
    try:
        import httpx
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        return any(EMBED_MODEL in m for m in models)
    except Exception:
        return False
