"""PiecesOS-style personal memory — who Matt is and what he's working on right now."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MCTABLE_ROOT = Path(os.getenv("MCHARNESS_DATA_ROOT", "_mctable"))
PROFILE_PATH = MCTABLE_ROOT / "personal_profile.json"

_DEFAULT_PROFILE: dict[str, Any] = {
    "name": "Matt McBride",
    "email": "matthewjmcbridejr@gmail.com",
    "bio": (
        "Software engineer and builder running a local-first agent OS on a personal server. "
        "Primary focus: Warden (supervised agent control room), Grademy (education platform), "
        "and Marius (personal AI assistant). Values: safety-first, proof-gated execution, "
        "local-first architecture, no arbitrary shell execution by agents."
    ),
    "active_projects": [
        "Warden",
        "Grademy",
        "Marius",
        "Hermes",
        "hybrid-agent-os",
    ],
    "current_priorities": [
        "Build Warden Agent OS v0.1 — Brain MCP + semantic memory",
        "Any agent should be able to recall Matt's full context via MCP",
        "Auto-ingest Obsidian vault and repos into Warden memory",
    ],
    "preferences": {
        "code_style": "Python, TypeScript; no magic; proof-oriented",
        "agent_trust": "agents read freely, writes gate through Warden proof gate",
        "infra": "local-first, server at home, Google Drive + rclone, Obsidian vault",
        "ai_models": "Claude Sonnet (default), Gemini for large context, Ollama for local",
    },
    "server_context": {
        "hostname": "linux server",
        "warden_port": 8125,
        "public_warden_port": 8124,
        "obsidian_vault": "~/Documents or ~/Obsidian",
        "repos_root": "/home/matt/workspaces",
    },
    "last_updated": datetime.now(timezone.utc).isoformat(),
}


def load_profile() -> dict[str, Any]:
    try:
        if PROFILE_PATH.exists():
            data = json.loads(PROFILE_PATH.read_text())
            # Merge in any missing default keys
            for k, v in _DEFAULT_PROFILE.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception as exc:
        log.warning("Could not load personal profile: %s", exc)
    return dict(_DEFAULT_PROFILE)


def update_profile(field: str, value: Any) -> dict[str, Any]:
    """Partial update — only touches the given field."""
    allowed = {"priorities", "projects", "preferences", "bio", "current_priorities", "active_projects"}
    # Normalise aliases
    field = {"priorities": "current_priorities", "projects": "active_projects"}.get(field, field)
    if field not in allowed and field not in _DEFAULT_PROFILE:
        raise ValueError(f"Unknown profile field: {field}")
    profile = load_profile()
    profile[field] = value
    profile["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save(profile)
    return profile


def _save(profile: dict[str, Any]) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, default=str))


def seed_if_missing() -> None:
    """Write default profile only if none exists yet."""
    if not PROFILE_PATH.exists():
        _save(_DEFAULT_PROFILE)
        log.info("Seeded personal profile at %s", PROFILE_PATH)


def get_workstream(limit: int = 10, project: str | None = None) -> list[dict]:
    """Most recent memories across all projects — the rolling 'what was I working on' feed."""
    try:
        from src.warden.workbench import WorkbenchStore
        store = WorkbenchStore()
        memories = store.list_memories()
        active = [m for m in memories if m.status != "forgotten"]
        workstream_kinds = {"decision", "proof", "failure", "handoff", "claim", "constraint"}
        active = [m for m in active if m.kind in workstream_kinds]
        if project:
            active = [m for m in active if (m.project_id or "").lower() == project.lower()
                      or m.scope.lower() == project.lower()]
        active.sort(key=lambda m: m.updated_at, reverse=True)
        return [
            {
                "memory_id": m.memory_id,
                "project": m.project_id or m.scope,
                "kind": m.kind,
                "title": m.title or m.summary[:60],
                "summary": m.summary[:200],
                "updated_at": m.updated_at.isoformat(),
                "tags": m.tags,
            }
            for m in active[:limit]
        ]
    except Exception as exc:
        log.warning("get_workstream failed: %s", exc)
        return []
