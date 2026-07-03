"""Dry-run Notion sync planning for Warden board tasks.

This module intentionally does not call the Notion API. It builds safe candidate
payloads so Warden can preview what would be promoted into a Notion inbox later.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BOARD_TASK_STATUSES = ("queued", "claimed", "running", "needs_review", "failed", "completed", "done")
NOTION_ENV_NAMES = (
    "NOTION_API_KEY",
    "NOTION_MASTER_INBOX_DATABASE_ID",
    "WARDEN_NOTION_WRITE_ENABLED",
)
TRUTHY = {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUTHY


def notion_write_enabled(env: Mapping[str, str] | None = None) -> bool:
    env = env or os.environ
    return _as_bool(env.get("WARDEN_NOTION_WRITE_ENABLED"))


def notion_sync_status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = env or os.environ
    return {
        "ok": True,
        "dry_run_available": True,
        "write_enabled": notion_write_enabled(env),
        "configured": {name: bool(env.get(name)) for name in NOTION_ENV_NAMES},
        "secrets_redacted": True,
    }


def _task_id(task: Mapping[str, Any]) -> str:
    return str(task.get("task_id") or task.get("id") or "").strip()


def _clean_text(value: Any, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return re.sub(r"\s+", " ", text)


def _normalize_key(value: Any) -> str:
    text = _clean_text(value).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _dedupe_key(candidate: Mapping[str, Any]) -> str:
    task_id = str(candidate.get("warden_task_id") or "").strip()
    if task_id:
        return f"task:{task_id}"
    bits = [candidate.get("title"), candidate.get("project"), candidate.get("source")]
    return "candidate:" + ":".join(_normalize_key(bit) for bit in bits)


def proof_status_for_task(task: Mapping[str, Any]) -> str:
    status = str(task.get("status") or "").lower()
    gate = str(task.get("proof_gate") or "").lower()
    if task.get("handoff") or gate == "handoff":
        return "handoff"
    if task.get("failure") or status == "failed" or gate in {"failed", "blocked"}:
        blocker = task.get("blocker") or (task.get("failure") or {}).get("blocker") if isinstance(task.get("failure"), dict) else ""
        return "blocked" if blocker else "failed"
    if gate == "verified" or task.get("proof") or task.get("proof_id"):
        return "verified"
    if status in {"completed", "done", "needs_review"} or task.get("proof_required", True):
        return "proof_needed"
    return "proof_needed"


def _safe_source_link(task: Mapping[str, Any]) -> str:
    task_id = _task_id(task)
    return f"warden://task/{task_id}" if task_id else "warden://task/untracked"


def build_notion_candidate_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    title = _clean_text(task.get("title"), "Untitled Warden task")
    summary = _clean_text(task.get("description") or task.get("summary"), "No summary recorded.")
    project = _clean_text(task.get("project") or task.get("project_id"), "Warden")
    created_at = _clean_text(task.get("created_at")) or _now()
    return {
        "warden_task_id": _task_id(task),
        "title": title,
        "project": project,
        "status": "candidate",
        "source": "warden",
        "type": "agent_task",
        "priority": _clean_text(task.get("priority"), "medium"),
        "ai_summary": summary,
        "proof_status": proof_status_for_task(task),
        "agent": _clean_text(task.get("agent") or task.get("assigned_agent"), "unassigned"),
        "repo_path": _clean_text(task.get("repo_path") or task.get("repo")),
        "branch": _clean_text(task.get("branch")),
        "created_at": created_at,
        "source_link": _safe_source_link(task),
    }


def _load_task_file(path: Path, status: str) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("status", status)
    data.setdefault("task_id", path.stem)
    return data


def build_candidate_tasks_from_board(board_root: str | Path, limit_per_status: int = 50) -> list[dict[str, Any]]:
    root = Path(board_root).expanduser()
    tasks_root = root / "tasks"
    candidates: list[dict[str, Any]] = []
    if not tasks_root.exists():
        return candidates
    for status in BOARD_TASK_STATUSES:
        status_dir = tasks_root / status
        if not status_dir.exists():
            continue
        for path in sorted(status_dir.glob("*.json"), reverse=True)[:limit_per_status]:
            task = _load_task_file(path, status)
            if task:
                candidates.append(build_notion_candidate_payload(task))
    return candidates


def dedupe_candidates(
    candidates: list[Mapping[str, Any]],
    existing_candidates: list[Mapping[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    seen = {_dedupe_key(item) for item in existing_candidates or []}
    unique: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in candidates:
        candidate = dict(item)
        key = _dedupe_key(candidate)
        if key in seen:
            skipped.append({**candidate, "skip_reason": "duplicate", "dedupe_key": key})
            continue
        seen.add(key)
        unique.append(candidate)
    return {"unique": unique, "skipped": skipped}


def sync_candidates_dry_run(
    board_root: str | Path,
    existing_candidates: list[Mapping[str, Any]] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    candidates = build_candidate_tasks_from_board(board_root)
    deduped = dedupe_candidates(candidates, existing_candidates=existing_candidates)
    return {
        "ok": True,
        "dry_run": True,
        "source": "warden_board",
        "generated_at": _now(),
        "candidates_found": len(candidates),
        "would_create_count": len(deduped["unique"]),
        "would_skip_count": len(deduped["skipped"]),
        "would_create": deduped["unique"],
        "would_skip": deduped["skipped"],
        "write_enabled": notion_write_enabled(env),
        "warnings": [],
    }


def sync_candidates_write(
    board_root: str | Path,
    existing_candidates: list[Mapping[str, Any]] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    status = notion_sync_status(env)
    preview = sync_candidates_dry_run(board_root, existing_candidates=existing_candidates, env=env)
    if not status["write_enabled"]:
        return {
            "ok": False,
            "blocked": True,
            "reason": "Notion writes are disabled. Set WARDEN_NOTION_WRITE_ENABLED=1 only after adding the real Notion writer.",
            "dry_run": True,
            "preview": preview,
        }
    return {
        "ok": False,
        "blocked": True,
        "reason": "Real Notion writes are not implemented in v0; dry-run preview is the supported path.",
        "dry_run": True,
        "preview": preview,
    }
