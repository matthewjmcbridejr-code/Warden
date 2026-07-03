"""Warden Workspace Authority v0.

Tells every agent where to code, what paths are scratch, which service
proves the work, and what safety rules apply — so agents never drift into
the wrong repo.

Config resolution order (first found wins):
  1. config/warden_projects.json  (repo-owned)
  2. ~/.config/warden/projects.json  (user override)
  3. Built-in defaults below
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------

_REPO_CONFIG = Path(__file__).resolve().parents[2] / "config" / "warden_projects.json"
_USER_CONFIG = Path("~/.config/warden/projects.json").expanduser()

# The current checkout, wherever it actually lives on this machine (Matt's
# box, CI, another dev's clone). Used as the default canonical repo for the
# "warden" project so the registry doesn't hardcode a path that only exists
# on one machine. A repo-owned or user config file can still override this.
_CURRENT_CHECKOUT = str(Path(__file__).resolve().parents[2])

# ---------------------------------------------------------------------------
# Built-in project registry (no config file needed)
# ---------------------------------------------------------------------------

_BUILTIN_REGISTRY: List[Dict[str, Any]] = [
    {
        "project_id": "warden",
        "display_name": "Warden / McTable",
        "canonical_repo": _CURRENT_CHECKOUT,
        "known_worktrees": [
            {
                "path": _CURRENT_CHECKOUT,
                "role": "canonical",
                "safe_to_edit": True,
            },
            {
                "path": "/home/matt/Documents/Warden",
                "role": "scratch_or_clone",
                "safe_to_edit": False,
            },
        ],
        "live_services": [
            {
                "name": "warden-local (port 6969)",
                "port": 6969,
                "url": "http://127.0.0.1:6969",
                "scope": "private",
            }
        ],
        "proof_commands": [
            "PYTHONPATH='.:src' .venv/bin/python -m py_compile src/warden/api.py",
            "node --check web/warden/command-deck.js",
            "PYTHONPATH='.:src' .venv/bin/pytest -q tests/test_warden_command_deck.py tests/test_warden_cockpit_static.py",
        ],
        "branch_policy": {
            "preserve_main": True,
            "prefer_feature_branch": True,
            "no_force_push": True,
        },
        "agent_start_rules": [
            "Verify pwd and git root before editing.",
            "Do not code in scratch/cloned repos unless explicitly assigned.",
            "Record proof or failure before closeout.",
            "Run proof_commands after every significant change.",
            "Never read, print, or commit .env files or secrets.",
        ],
    },
    {
        "project_id": "marius",
        "display_name": "Marius Core",
        "canonical_repo": "/home/matt/workspaces/marius-core",
        "known_worktrees": [
            {
                "path": "/home/matt/workspaces/marius-core",
                "role": "canonical",
                "safe_to_edit": True,
            }
        ],
        "live_services": [],
        "proof_commands": [],
        "branch_policy": {
            "preserve_main": True,
            "prefer_feature_branch": True,
            "no_force_push": True,
        },
        "agent_start_rules": [
            "Verify pwd and git root before editing.",
            "Record proof or failure before closeout.",
        ],
    },
]


# ---------------------------------------------------------------------------
# Registry loader
# ---------------------------------------------------------------------------

def _load_registry() -> List[Dict[str, Any]]:
    for cfg_path in (_REPO_CONFIG, _USER_CONFIG):
        if cfg_path.exists():
            try:
                loaded = json.loads(cfg_path.read_text())
                if isinstance(loaded, list):
                    # Merge: user entries override built-ins by project_id
                    builtin_by_id = {p["project_id"]: p for p in _BUILTIN_REGISTRY}
                    for entry in loaded:
                        builtin_by_id[entry["project_id"]] = {**builtin_by_id.get(entry["project_id"], {}), **entry}
                    return list(builtin_by_id.values())
            except Exception:
                pass
    return list(_BUILTIN_REGISTRY)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

WorkspaceStatus = Literal["canonical", "known_worktree", "non_canonical", "unknown"]


def resolve_project(project_id: str) -> Optional[Dict[str, Any]]:
    """Return the project registry entry or None."""
    for p in _load_registry():
        if p["project_id"] == project_id:
            return p
    return None


def list_projects() -> List[Dict[str, Any]]:
    return _load_registry()


def get_canonical_repo(project_id: str) -> Optional[str]:
    p = resolve_project(project_id)
    return p.get("canonical_repo") if p else None


def classify_worktree(project_id: str, path: str) -> Dict[str, Any]:
    """Classify a path relative to a project's known worktrees."""
    p = resolve_project(project_id)
    if not p:
        return {
            "workspace_status": "unknown",
            "safe_to_edit": False,
            "message": f"Unknown project: {project_id!r}",
        }

    normalized = str(Path(path).expanduser().resolve())
    canonical = str(Path(p.get("canonical_repo", "")).expanduser().resolve())

    for wt in p.get("known_worktrees", []):
        wt_path = str(Path(wt["path"]).expanduser().resolve())
        if normalized == wt_path or normalized.startswith(wt_path + "/"):
            role = wt.get("role", "unknown")
            safe = bool(wt.get("safe_to_edit", False))
            status: WorkspaceStatus = "canonical" if role == "canonical" else "known_worktree"
            result: Dict[str, Any] = {
                "workspace_status": status,
                "safe_to_edit": safe,
                "role": role,
                "matched_worktree": wt_path,
            }
            if not safe:
                result["message"] = (
                    f"Do not code here. Use {canonical}."
                )
            return result

    # Path not in any known worktree
    return {
        "workspace_status": "non_canonical",
        "safe_to_edit": False,
        "message": f"Path is not a registered worktree for {project_id!r}. Use {canonical}.",
    }


def detect_workspace_drift(project_id: str, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Detect if the agent is operating in the wrong workspace."""
    effective_cwd = cwd or os.getcwd()
    classification = classify_worktree(project_id, effective_cwd)
    drifted = not classification.get("safe_to_edit", False)
    return {
        "project_id": project_id,
        "cwd": effective_cwd,
        "drifted": drifted,
        **classification,
    }


def build_agent_bootstrap(
    project_id: str,
    task: str = "",
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a full agent bootstrap packet for a project + task."""
    p = resolve_project(project_id)
    if not p:
        return {
            "ok": False,
            "error": f"Unknown project: {project_id!r}",
            "project_id": project_id,
        }

    effective_cwd = cwd or os.getcwd()
    drift = detect_workspace_drift(project_id, effective_cwd)
    canonical = p.get("canonical_repo", "")

    canonical_wts = [
        wt for wt in p.get("known_worktrees", []) if wt.get("safe_to_edit")
    ]
    scratch_wts = [
        wt for wt in p.get("known_worktrees", []) if not wt.get("safe_to_edit")
    ]

    warnings: List[str] = []
    if drift["drifted"]:
        warnings.append(
            f"WARNING: You are in {effective_cwd!r} which is NOT canonical. "
            f"Do not make edits here. Switch to: {canonical}"
        )

    return {
        "ok": True,
        "project_id": project_id,
        "display_name": p.get("display_name", project_id),
        "task": task,
        "canonical_repo": canonical,
        "code_here": canonical_wts,
        "do_not_code_here": scratch_wts,
        "live_services": p.get("live_services", []),
        "proof_commands": p.get("proof_commands", []),
        "branch_policy": p.get("branch_policy", {}),
        "agent_start_rules": p.get("agent_start_rules", []),
        "cwd_classification": drift,
        "warnings": warnings,
        "recommended_next_action": (
            f"Switch to {canonical} and run: git status --short"
            if drift["drifted"]
            else "You are in the canonical repo. Proceed with the task."
        ),
    }
