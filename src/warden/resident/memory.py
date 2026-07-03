"""Thin memory adapter over personal_memory.py / memory_agent.py.

Every result carries a source id and created_at so replies can cite where
information came from. Search results are capped (default 5) to keep
context/token usage bounded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DEFAULT_SEARCH_LIMIT = 5


@dataclass
class MemoryResult:
    source_id: str
    summary: str
    created_at: str
    kind: str = "memory"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "summary": self.summary,
            "created_at": self.created_at,
            "kind": self.kind,
        }


class MemoryAdapter:
    """Wraps warden.personal_memory (workstream) + warden.memory_agent (context)
    for resident-facing memory operations. Falls back gracefully when the
    underlying stores are unavailable (e.g. no board/workbench configured)."""

    def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[MemoryResult]:
        limit = max(1, min(limit, DEFAULT_SEARCH_LIMIT))
        results: list[MemoryResult] = []
        try:
            from ..memory_agent import _recent_memories  # type: ignore
            mems = _recent_memories(query=query, limit=limit)
            for m in mems[:limit]:
                results.append(
                    MemoryResult(
                        source_id=str(m.get("memory_id", m.get("id", ""))),
                        summary=str(m.get("summary", m.get("content", "")))[:300],
                        created_at=str(m.get("created_at", "")),
                        kind=str(m.get("kind", "memory")),
                    )
                )
        except Exception:
            pass
        return results[:limit]

    def recent(self, limit: int = DEFAULT_SEARCH_LIMIT, project: str | None = None) -> list[MemoryResult]:
        limit = max(1, min(limit, DEFAULT_SEARCH_LIMIT))
        results: list[MemoryResult] = []
        try:
            from ..personal_memory import get_workstream
            items = get_workstream(limit=limit, project=project)
            for it in items[:limit]:
                results.append(
                    MemoryResult(
                        source_id=str(it.get("memory_id", "")),
                        summary=str(it.get("summary", it.get("title", "")))[:300],
                        created_at=str(it.get("updated_at", "")),
                        kind=str(it.get("kind", "memory")),
                    )
                )
        except Exception:
            pass
        return results[:limit]

    def remember(self, note: str, category: str = "resident") -> MemoryResult:
        """Save a note. Prefers marius.memory.save_fact (simple, local, no deps);
        falls back to a plain audit-only record if unavailable."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            from marius import memory as marius_memory  # type: ignore
            marius_memory.save_fact(note, category=category)
            return MemoryResult(source_id=f"note-{int(datetime.now().timestamp())}", summary=note[:300],
                                 created_at=now, kind="note")
        except Exception:
            return MemoryResult(source_id="note-unsaved", summary=note[:300], created_at=now, kind="note_failed")
