"""PiecesOS-style personal memory — who the operator is and what they're working on."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from src.warden.paths import data_root as _warden_data_root
MCTABLE_ROOT = _warden_data_root()
PROFILE_PATH = MCTABLE_ROOT / "personal_profile.json"

# Seeded only when no profile exists yet (seed_if_missing) — existing installs
# keep their saved profile untouched. Deliberately generic: the name falls back
# to the OS username so a fresh install never introduces itself as someone else;
# the owner personalizes via warden_update_me or the UI.
def _default_profile() -> dict[str, Any]:
    import getpass

    try:
        username = getpass.getuser()
    except Exception:
        username = "operator"
    return {
        "name": username,
        "email": "",
        "bio": (
            "Warden operator. Update this profile (warden_update_me or the UI) so "
            "agents get real context: who you are, what you're building, how you work."
        ),
        "active_projects": ["Warden"],
        "current_priorities": [
            "Productize Warden as a multi-agent operating/control layer.",
            "Build Warden Control Plane v1: Actions + Decisions + Capability Grants + Approvals.",
            "Keep cross-agent context revision-first, cheap, and automatic.",
            "Preserve evidence and proof for consequential agent actions.",
            "Prepare Warden for a sanitized public portfolio/demo distribution.",
        ],
        "preferences": {
            "agent_trust": "agents read freely, writes gate through Warden proof gate",
        },
        "server_context": {
            "repos_root": str(Path.home() / "workspaces"),
        },
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


_DEFAULT_PROFILE: dict[str, Any] = _default_profile()


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
