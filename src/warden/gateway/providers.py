"""Provider health checks — reachability and key presence, no secrets exposed."""
from __future__ import annotations

import os
import time
import urllib.request
from typing import Any

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
LITELLM_URL = os.getenv("LITELLM_GATEWAY_URL", "http://127.0.0.1:4000")
CRAWL4AI_URL = os.getenv("CRAWL4AI_SERVICE_URL", "http://127.0.0.1:8099")


def _ping(url: str, timeout: float = 3.0) -> tuple[bool, int]:
    """Returns (reachable, latency_ms)."""
    t0 = time.time()
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True, int((time.time() - t0) * 1000)
    except Exception:
        return False, 0


def _key_present(env_var: str) -> bool:
    v = os.getenv(env_var, "")
    return bool(v and len(v) > 8)


def check_all() -> list[dict[str, Any]]:
    results = []

    # Ollama
    ok, ms = _ping(f"{OLLAMA_URL}/api/tags")
    ollama_models: list[str] = []
    if ok:
        try:
            import json
            with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
                data = json.loads(r.read())
            ollama_models = [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
    results.append({
        "provider": "Ollama",
        "status": "reachable" if ok else "unreachable",
        "latency_ms": ms,
        "key_configured": True,  # local, no key
        "models_available": len(ollama_models),
        "note": f"{len(ollama_models)} models loaded" if ok else "not running",
    })

    # Groq
    results.append({
        "provider": "Groq",
        "status": "configured" if _key_present("GROQ_API_KEY") else "no-key",
        "latency_ms": None,
        "key_configured": _key_present("GROQ_API_KEY"),
        "note": "Free tier — llama-3.1-8b-instant, llama-3.3-70b-versatile",
    })

    # Cerebras
    results.append({
        "provider": "Cerebras",
        "status": "configured" if _key_present("CEREBRAS_API_KEY") else "no-key",
        "latency_ms": None,
        "key_configured": _key_present("CEREBRAS_API_KEY"),
        "note": "Free tier — llama3.1-8b, llama-3.3-70b",
    })

    # OpenRouter
    results.append({
        "provider": "OpenRouter",
        "status": "configured" if _key_present("OPENROUTER_API_KEY") else "no-key",
        "latency_ms": None,
        "key_configured": _key_present("OPENROUTER_API_KEY"),
        "note": "Free models may log prompts — warden-free only",
    })

    # HuggingFace
    results.append({
        "provider": "HuggingFace",
        "status": "configured" if _key_present("HF_TOKEN") else "no-key",
        "latency_ms": None,
        "key_configured": _key_present("HF_TOKEN"),
        "note": "Embeddings and specialty models",
    })

    # Tavily
    results.append({
        "provider": "Tavily",
        "status": "configured" if _key_present("TAVILY_API_KEY") else "no-key",
        "latency_ms": None,
        "key_configured": _key_present("TAVILY_API_KEY"),
        "note": "Web search — used by WardenAgent web_search tool",
    })

    # Crawl4AI
    ok_c, ms_c = _ping(f"{CRAWL4AI_URL}/health")
    results.append({
        "provider": "Crawl4AI",
        "status": "reachable" if ok_c else "unreachable",
        "latency_ms": ms_c if ok_c else None,
        "key_configured": True,
        "note": "Local crawl service on :8099" if ok_c else "service not running",
    })

    # LiteLLM proxy
    ok_l, ms_l = _ping(f"{LITELLM_URL}/health")
    results.append({
        "provider": "LiteLLM Gateway",
        "status": "reachable" if ok_l else "unreachable",
        "latency_ms": ms_l if ok_l else None,
        "key_configured": True,
        "note": f"Proxy on :4000 — 6 aliases" if ok_l else "proxy not running",
    })

    return results
