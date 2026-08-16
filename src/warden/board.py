"""Warden Board and Task Lifecycle Management.

Provides authoritative task board storage operations, first-class task lifecycle
state transitions (update, cancel, supersede, revalidate), and lightweight
dependency justification links between decisions, tasks, claims, and proofs.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from src.warden.paths import data_root

ALL_TASK_STATUSES = (
    "draft",
    "assigned",
    "claimed",
    "blocked",
    "needs_review",
    "completed",
    "cancelled",
    "superseded",
)

ACTIVE_TASK_STATUSES = (
    "draft",
    "assigned",
    "claimed",
    "blocked",
    "needs_review",
)


def get_board_root() -> Path:
    env = os.getenv("WARDEN_BOARD_ROOT") or os.getenv("MCTABLE_BOARD_ROOT")
    if env:
        return Path(env).expanduser()
    return data_root() / "board"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug_task_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower().strip())[:40].strip("-")
    short = str(uuid.uuid4())[:6]
    return f"{slug}-{short}"


def _task_dir(status: str) -> Path:
    d = get_board_root() / "tasks" / status
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_task(task_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    """Find a task across all status directories."""
    board = get_board_root()
    tasks_dir = board / "tasks"
    if not tasks_dir.exists():
        return None, None

    for status in ALL_TASK_STATUSES:
        candidate = tasks_dir / status / f"{task_id}.json"
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                data["_status"] = status
                data["_path"] = str(candidate)
                return data, candidate
            except Exception:
                pass
    return None, None


def list_tasks(project: str = "", status: str = "") -> List[Dict[str, Any]]:
    """List tasks filtered by optional project and/or status."""
    board = get_board_root()
    tasks_dir = board / "tasks"
    if not tasks_dir.exists():
        return []

    statuses = [status] if status else ALL_TASK_STATUSES
    tasks: List[Dict[str, Any]] = []

    for st in statuses:
        sdir = tasks_dir / st
        if not sdir.exists():
            continue
        for p in sorted(sdir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                data["_status"] = st
                data["_path"] = str(p)
                if project and str(data.get("project") or "").lower() != project.strip().lower():
                    continue
                tasks.append(data)
            except Exception:
                continue

    return tasks


def update_task(task_id: str, updates: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Update metadata fields of an existing task while preserving history and file location."""
    task, path = find_task(task_id)
    if not task or not path:
        raise FileNotFoundError(f"Task {task_id} not found.")

    allowed_fields = {
        "title",
        "description",
        "agent",
        "project",
        "priority",
        "files",
        "based_on",
        "branch",
        "metadata",
    }

    for key, val in updates.items():
        if key in allowed_fields:
            task[key] = val

    task["updated_at"] = _now_iso()
    if actor:
        task["updated_by"] = actor

    # Remove internal keys before writing
    clean_task = {k: v for k, v in task.items() if not k.startswith("_")}
    path.write_text(json.dumps(clean_task, indent=2), encoding="utf-8")
    clean_task["_status"] = task.get("_status")
    clean_task["_path"] = str(path)
    return clean_task


def cancel_task(task_id: str, reason: str, actor: str = "") -> Dict[str, Any]:
    """Cancel a task, moving it to tasks/cancelled while preserving full history."""
    task, path = find_task(task_id)
    if not task or not path:
        raise FileNotFoundError(f"Task {task_id} not found.")

    now = _now_iso()
    task["status"] = "cancelled"
    task["cancelled_at"] = now
    task["cancelled_by"] = actor or "warden"
    task["cancel_reason"] = reason
    task["updated_at"] = now

    dest_dir = _task_dir("cancelled")
    dest_path = dest_dir / f"{task_id}.json"

    clean_task = {k: v for k, v in task.items() if not k.startswith("_")}
    dest_path.write_text(json.dumps(clean_task, indent=2), encoding="utf-8")
    if dest_path != path:
        path.unlink(missing_ok=True)

    clean_task["_status"] = "cancelled"
    clean_task["_path"] = str(dest_path)
    return clean_task


def supersede_task(
    task_id: str,
    reason: str,
    actor: str = "",
    superseded_by_task: str = "",
    superseded_by_decision: str = "",
) -> Dict[str, Any]:
    """Mark a task superseded by a newer decision or task, preserving full history."""
    task, path = find_task(task_id)
    if not task or not path:
        raise FileNotFoundError(f"Task {task_id} not found.")

    now = _now_iso()
    task["status"] = "superseded"
    task["superseded_at"] = now
    task["superseded_by"] = actor or "warden"
    task["supersede_reason"] = reason
    if superseded_by_task:
        task["superseded_by_task"] = superseded_by_task
    if superseded_by_decision:
        task["superseded_by_decision"] = superseded_by_decision
    task["updated_at"] = now

    dest_dir = _task_dir("superseded")
    dest_path = dest_dir / f"{task_id}.json"

    clean_task = {k: v for k, v in task.items() if not k.startswith("_")}
    dest_path.write_text(json.dumps(clean_task, indent=2), encoding="utf-8")
    if dest_path != path:
        path.unlink(missing_ok=True)

    clean_task["_status"] = "superseded"
    clean_task["_path"] = str(dest_path)
    return clean_task


def revalidate_task_or_claim(task_id: str) -> Dict[str, Any]:
    """Revalidate whether a task or claim remains valid active work."""
    task, path = find_task(task_id)
    if not task:
        return {
            "task_id": task_id,
            "valid": False,
            "status": "not_found",
            "reason": f"Task {task_id} does not exist on board.",
        }

    status = task.get("status") or task.get("_status")
    if status in ("cancelled", "superseded", "completed"):
        return {
            "task_id": task_id,
            "valid": False,
            "status": status,
            "reason": f"Task is {status}: {task.get('cancel_reason') or task.get('supersede_reason') or 'Work complete or invalidated'}",
            "task": task,
        }

    return {
        "task_id": task_id,
        "valid": True,
        "status": status,
        "reason": "Task is active work.",
        "task": task,
    }


def get_work_dependent_on_decision(decision_id: str, project: str = "") -> Dict[str, Any]:
    """Traverse decision -> tasks -> claims -> runs -> proofs to find work depending on a decision."""
    tasks = list_tasks(project=project)
    dependent_tasks: List[Dict[str, Any]] = []

    for t in tasks:
        based_on = t.get("based_on") or []
        if isinstance(based_on, str):
            based_on = [based_on]
        if decision_id in based_on or str(t.get("superseded_by_decision") or "") == decision_id:
            dependent_tasks.append(t)
        elif decision_id.lower() in json.dumps(t).lower():
            dependent_tasks.append(t)

    # Collect claims for these dependent tasks
    board = get_board_root()
    claims_dir = board / "claims"
    dependent_claims: List[Dict[str, Any]] = []
    task_ids = {t.get("task_id") for t in dependent_tasks}

    if claims_dir.exists():
        for claim_file in claims_dir.glob("*.json"):
            try:
                claim = json.loads(claim_file.read_text(encoding="utf-8"))
                if claim.get("task") in task_ids:
                    dependent_claims.append(claim)
            except Exception:
                pass

    return {
        "decision_id": decision_id,
        "dependent_tasks": dependent_tasks,
        "dependent_claims": dependent_claims,
        "task_count": len(dependent_tasks),
        "claim_count": len(dependent_claims),
    }
