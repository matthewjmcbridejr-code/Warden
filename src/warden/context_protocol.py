"""Revisioned Context Delta Protocol for Warden MCP 2.0.

Provides scoped context revision hashing and delta calculation to eliminate
repetitive context shipping to connected MCP clients and agents.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# In-memory bounded journal of recent context revisions & changes
_REVISION_JOURNAL: list[dict[str, Any]] = []
_MAX_JOURNAL_SIZE = 100


def compute_context_revision(
    project: str = "",
    tasks: list[dict[str, Any]] | None = None,
    memories: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> str:
    """Computes a deterministic hash representing context state for a given project scope.

    Must ONLY change when project truth (decisions, constraints, tasks, claims, blockers)
    changes. Must NOT change due to timestamps, health checks, or unrelated project state.
    """
    items: list[str] = []
    proj_lower = (project or "").lower()

    if memories:
        for m in memories:
            p = (m.get("project") or m.get("project_id") or "").lower()
            kind = m.get("kind") or ""
            if (not proj_lower or p == proj_lower or p == "all") and kind in ("decision", "constraint", "proof"):
                mem_id = m.get("memory_id") or m.get("title") or ""
                text = m.get("title") or m.get("summary") or m.get("text") or ""
                items.append(f"mem:{mem_id}:{kind}:{text}")

    if tasks:
        for t in tasks:
            p = t.get("project") or ""
            if not project or p == project:
                task_id = t.get("task_id") or ""
                status = t.get("status") or ""
                title = t.get("title") or ""
                items.append(f"task:{task_id}:{status}:{title}")

    if claims:
        for c in claims:
            p = c.get("project") or ""
            if not project or p == project:
                claim_id = c.get("claim_id") or ""
                status = c.get("status") or ""
                statement = c.get("statement") or ""
                items.append(f"claim:{claim_id}:{status}:{statement}")

    items.sort()
    payload = json.dumps({"project": project, "items": items}, sort_keys=True)
    return "ctx_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def record_context_change(
    revision: str,
    project: str,
    category: str, # decisions, tasks, claims, blockers
    action: str, # added, updated, removed
    item: dict[str, Any],
) -> None:
    """Records a context change entry in the bounded revision journal."""
    entry = {
        "revision": revision,
        "project": project,
        "category": category,
        "action": action,
        "item": item,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _REVISION_JOURNAL.append(entry)
    if len(_REVISION_JOURNAL) > _MAX_JOURNAL_SIZE:
        _REVISION_JOURNAL.pop(0)


def get_context_delta(
    since_revision: str,
    current_revision: str,
    project: str = "",
    tasks: list[dict[str, Any]] | None = None,
    memories: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Computes a context delta payload relative to since_revision."""
    if not since_revision or since_revision == current_revision:
        return {
            "from_revision": since_revision or current_revision,
            "to_revision": current_revision,
            "changed": False,
        }

    # Find changes in journal since target revision
    matching = [e for e in _REVISION_JOURNAL if e["revision"] != since_revision and (not project or e["project"] == project)]

    if not matching and len(_REVISION_JOURNAL) >= _MAX_JOURNAL_SIZE:
        return {
            "from_revision": since_revision,
            "to_revision": current_revision,
            "changed": True,
            "delta_unavailable": True,
            "requires_bootstrap": True,
        }

    added: dict[str, list[dict[str, Any]]] = {"decisions": [], "tasks": [], "claims": []}
    updated: dict[str, list[dict[str, Any]]] = {"tasks": [], "claims": []}
    removed: dict[str, list[dict[str, Any]]] = {"tasks": [], "claims": []}

    for entry in matching:
        cat = entry["category"]
        act = entry["action"]
        item = entry["item"]
        if act == "added" and cat in added:
            added[cat].append(item)
        elif act == "updated" and cat in updated:
            updated[cat].append(item)
        elif act == "removed" and cat in removed:
            removed[cat].append(item)

    # Fallback to current items if journal has no specific entry
    if not any(added.values()) and not any(updated.values()) and not any(removed.values()):
        added["decisions"] = [m for m in (memories or []) if m.get("kind") == "decision"]
        updated["tasks"] = tasks or []
        updated["claims"] = claims or []

    return {
        "from_revision": since_revision,
        "to_revision": current_revision,
        "changed": True,
        "added": added,
        "updated": updated,
        "removed": removed,
    }
