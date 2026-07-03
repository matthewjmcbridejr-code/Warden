from __future__ import annotations

import os
from typing import Any


def _env_flag(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


class GoogleRAGAdapter:
    provider = "google-rag"

    def is_enabled(self) -> bool:
        return _env_flag("WARDEN_GOOGLE_RAG_ENABLED", default="false")

    def status_payload(self) -> dict[str, Any]:
        enabled = self.is_enabled()
        payload = {
            "provider": self.provider,
            "enabled": enabled,
            "configured": False,
            "warning": "",
        }
        if not enabled:
            payload["warning"] = "Google RAG is disabled by default for this local Warden build."
        return payload

    def fetch_context(self, query: str, max_chars: int = 1200) -> dict[str, Any]:
        payload = self.status_payload()
        payload["query"] = (query or "").strip()[:500]
        payload["max_chars"] = max(256, min(max_chars, 4000))
        payload["context"] = ""
        payload["sources"] = []
        return payload


GOOGLE_RAG_ADAPTER = GoogleRAGAdapter()
