"""Google Brain provider — Vertex AI Search / Discovery Engine.

Reads config from WARDEN_GOOGLE_BRAIN_* env vars.
Discovery Engine client is optional; returns configured=false with setup hint if missing.
No real network calls in tests — use set_search_client_factory() to inject a mock.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Optional

from .models import BrainAnswer, BrainCitation, BrainChunk

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _cfg(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def is_enabled() -> bool:
    return _cfg("WARDEN_GOOGLE_BRAIN_ENABLED", "0") == "1"


def get_config() -> dict:
    return {
        "project_id": _cfg("WARDEN_GOOGLE_PROJECT_ID"),
        "location": _cfg("WARDEN_GOOGLE_LOCATION", "global"),
        "data_store_id": _cfg("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID"),
        # Engine ID is optional — used when serving config is under engines/ path
        "engine_id": _cfg("WARDEN_GOOGLE_DISCOVERY_ENGINE_ENGINE_ID"),
        "serving_config": _cfg("WARDEN_GOOGLE_DISCOVERY_ENGINE_SERVING_CONFIG", "default_search"),
        "collection_id": _cfg("WARDEN_GOOGLE_BRAIN_COLLECTION_ID", "default_collection"),
        "credentials_file": _cfg("WARDEN_GOOGLE_APPLICATION_CREDENTIALS"),
    }


def _serving_config_path(cfg: dict) -> str:
    """Build the canonical serving config resource path."""
    base = f"projects/{cfg['project_id']}/locations/{cfg['location']}/collections/{cfg['collection_id']}"
    if cfg.get("engine_id"):
        return f"{base}/engines/{cfg['engine_id']}/servingConfigs/{cfg['serving_config']}"
    return f"{base}/dataStores/{cfg['data_store_id']}/servingConfigs/{cfg['serving_config']}"


def is_configured() -> bool:
    cfg = get_config()
    return bool(cfg["project_id"] and cfg["data_store_id"])


# ---------------------------------------------------------------------------
# Client injection for testing
# ---------------------------------------------------------------------------

_search_client_factory = None  # callable() -> fake client


def set_search_client_factory(fn):
    global _search_client_factory
    _search_client_factory = fn


def _get_client():
    if _search_client_factory is not None:
        return _search_client_factory(), None
    creds_file = _cfg("WARDEN_GOOGLE_APPLICATION_CREDENTIALS")
    if creds_file:
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", creds_file)
    try:
        from google.cloud import discoveryengine_v1 as de
        return de.SearchServiceClient(), None
    except ImportError:
        return None, "google-cloud-discoveryengine not installed. Run: pip install google-cloud-discoveryengine"
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Provider status
# ---------------------------------------------------------------------------

def status() -> dict:
    cfg = get_config()
    client, client_error = _get_client()
    return {
        "provider": "google_discovery_engine",
        "enabled": is_enabled(),
        "configured": is_configured(),
        "available": client is not None and is_configured(),
        "project_id": cfg["project_id"],
        "location": cfg["location"],
        "data_store_id": cfg["data_store_id"],
        "serving_config": cfg["serving_config"],
        "collection_id": cfg["collection_id"],
        "credentials_configured": bool(cfg["credentials_file"]),
        "last_error": client_error,
        "capabilities": ["search", "answer", "mirror_documents", "source_citations"],
        "setup_required": [] if is_configured() else [
            "WARDEN_GOOGLE_BRAIN_ENABLED=1",
            "WARDEN_GOOGLE_PROJECT_ID=<your-project-id>",
            "WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID=<your-datastore-id>",
            "WARDEN_GOOGLE_APPLICATION_CREDENTIALS=<path-to-service-account.json>",
        ],
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(query: str, limit: int = 10) -> list[dict]:
    """Search Google Discovery Engine. Returns result dicts compatible with local provider."""
    if not is_enabled():
        return []
    if not is_configured():
        return [{"error": "Google Brain not configured", "provider": "google_discovery_engine"}]

    cfg = get_config()
    client, client_error = _get_client()
    if client is None:
        return [{"error": client_error, "provider": "google_discovery_engine"}]

    try:
        serving_path = _serving_config_path(cfg)

        # Handle real vs fake client
        if _search_client_factory is not None:
            # Fake client protocol: client.search(serving_config, query, page_size)
            raw_results = client.search(serving_path, query, limit)
        else:
            from google.cloud import discoveryengine_v1 as de
            req = de.SearchRequest(
                serving_config=serving_path,
                query=query,
                page_size=limit,
            )
            raw_results = list(client.search(req))

        results = []
        for r in raw_results:
            doc = getattr(r, "document", r)
            data = getattr(doc, "derived_struct_data", {}) or {}
            snippet = ""
            if "snippets" in data and data["snippets"]:
                snippet = data["snippets"][0].get("snippet", "")
            elif "extractive_answers" in data and data["extractive_answers"]:
                snippet = data["extractive_answers"][0].get("content", "")
            results.append({
                "source_path": data.get("link", getattr(doc, "name", "")),
                "title": data.get("title", getattr(doc, "id", "")),
                "heading": "",
                "excerpt": snippet[:400],
                "provider": "google_discovery_engine",
                "score": 1.0,
            })
        return results

    except Exception as exc:
        log.warning("Google Brain search failed: %s", exc)
        return [{"error": f"Google search failed: {exc}", "provider": "google_discovery_engine"}]


# ---------------------------------------------------------------------------
# Extractive answer
# ---------------------------------------------------------------------------

def answer(question: str, limit: int = 6) -> BrainAnswer:
    """Query Google Discovery Engine and compose a BrainAnswer."""
    if not is_enabled():
        return BrainAnswer(
            answer="Google Brain is not enabled (WARDEN_GOOGLE_BRAIN_ENABLED=1 required).",
            provider_used="google_discovery_engine",
            errors=["Google Brain disabled"],
        )

    results = search(question, limit=limit)
    errors = [r["error"] for r in results if "error" in r]
    valid = [r for r in results if "error" not in r]

    if not valid:
        return BrainAnswer(
            answer="Google Brain returned no results.",
            provider_used="google_discovery_engine",
            google_count=0,
            errors=errors,
        )

    citations = [
        BrainCitation(
            source_path=r.get("source_path", ""),
            title=r.get("title", ""),
            heading=r.get("heading", ""),
            excerpt=r.get("excerpt", ""),
            provider="google_discovery_engine",
            score=r.get("score", 1.0),
        )
        for r in valid
    ]
    answer_text = "\n\n".join(c.excerpt for c in citations[:3] if c.excerpt)
    return BrainAnswer(
        answer=answer_text or "Google Brain returned results without extractable text.",
        citations=citations,
        confidence=min(0.9, 0.3 * len(citations)),
        provider_used="google_discovery_engine",
        google_count=len(valid),
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Verify config (lightweight connectivity test)
# ---------------------------------------------------------------------------

def verify_config() -> dict:
    """Try a dummy search to verify Google credentials work."""
    if not is_enabled():
        return {"ok": False, "reason": "WARDEN_GOOGLE_BRAIN_ENABLED is not set to 1"}
    if not is_configured():
        return {"ok": False, "reason": "Missing WARDEN_GOOGLE_PROJECT_ID or WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID"}
    results = search("warden test", limit=1)
    if results and "error" in results[0]:
        return {"ok": False, "reason": results[0]["error"]}
    return {"ok": True, "results_count": len(results)}
