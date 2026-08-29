"""Persistent Captain supervised plans and step progression."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

_FILE_LOCK = threading.Lock()

STEP_STATUSES = frozenset({
    "queued",
    "dispatched",
    "running",
    "needs_review",
    "passed",
    "failed",
    "revised",
    "skipped",
    "stopped",
})

PLAN_STATUSES = frozenset({"active", "stopped", "completed"})

DISPATCHABLE_STEP_STATUSES = frozenset({"queued", "revised", "needs_review", "dispatched"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cloud_plane():
    from .cloud_control_plane import CloudControlPlane, cloud_control_enabled
    return CloudControlPlane() if cloud_control_enabled() else None


def _sync_cloud_plan(plan: dict[str, Any]) -> None:
    plane = _cloud_plane()
    if plane is None:
        return
    try:
        plane.upsert_record("mission_plan", str(plan["plan_id"]), plan, source_updated_at=plan.get("updated_at"))
    except Exception:
        plane.enqueue_record("mission_plan", str(plan["plan_id"]), plan)


def _cloud_plan(plan_id: str) -> dict[str, Any] | None:
    plane = _cloud_plane()
    if plane is None:
        return None
    try:
        return plane.get_record("mission_plan", plan_id)
    except Exception:
        return None


def plans_index_path(root: Path) -> Path:
    return root / "captain" / "plans.json"


def _read_plans(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to read Captain plans index.") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="Invalid Captain plans index format.")
    return data


def _write_plans(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _prompt_preview(prompt: str, limit: int = 280) -> str:
    text = (prompt or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def normalize_step(raw: dict[str, Any], *, order: int) -> dict[str, Any]:
    now = _now_iso()
    step_id = str(raw.get("step_id") or raw.get("id") or f"step_{order}")
    return {
        "step_id": step_id,
        "order": order,
        "title": str(raw.get("title") or f"Step {order}").strip(),
        "prompt": str(raw.get("prompt") or "").strip(),
        "agent_id": str(raw.get("agent_id") or raw.get("agent") or "codex_cli"),
        "status": str(raw.get("status") or "queued"),
        "run_id": raw.get("run_id"),
        "evidence_ids": list(raw.get("evidence_ids") or []),
        "created_at": raw.get("created_at") or now,
        "updated_at": raw.get("updated_at") or now,
    }


def _sorted_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(steps, key=lambda step: int(step.get("order") or 0))


def _find_step(plan: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in plan.get("steps") or []:
        if step.get("step_id") == step_id or step.get("id") == step_id:
            return step
    raise HTTPException(status_code=404, detail=f"Captain plan step not found: {step_id}")


def _first_queued_step_id(plan: dict[str, Any]) -> str | None:
    for step in _sorted_steps(plan.get("steps") or []):
        if step.get("status") in {"queued", "revised"}:
            return str(step.get("step_id"))
    return None


def _next_queued_step_id(plan: dict[str, Any], after_step_id: str) -> str | None:
    steps = _sorted_steps(plan.get("steps") or [])
    seen = False
    for step in steps:
        if step.get("step_id") == after_step_id:
            seen = True
            continue
        if seen and step.get("status") in {"queued", "revised"}:
            return str(step.get("step_id"))
    return None


def append_decision_log(plan: dict[str, Any], *, action: str, detail: str, step_id: str | None = None) -> None:
    log = list(plan.get("decision_log") or [])
    log.insert(0, {
        "at": _now_iso(),
        "action": action,
        "detail": detail,
        "step_id": step_id,
    })
    plan["decision_log"] = log[:100]


def persist_plan(
    root: Path,
    *,
    goal: str,
    repo_id: str | None,
    plan_data: dict[str, Any],
    status: str = "active",
) -> dict[str, Any]:
    now = _now_iso()
    plan_id = str(plan_data.get("plan_id") or f"plan_{uuid.uuid4().hex[:8]}")
    raw_steps = plan_data.get("steps") or []
    steps = [normalize_step(step, order=index) for index, step in enumerate(raw_steps, start=1)]
    if not steps:
        raise HTTPException(status_code=400, detail="Captain plan must include at least one step.")
    current_step_id = str(plan_data.get("current_step_id") or steps[0]["step_id"])
    record = {
        "plan_id": plan_id,
        "goal": goal.strip(),
        "title": str(plan_data.get("title") or "Captain plan").strip(),
        "summary": str(plan_data.get("summary") or goal).strip(),
        "repo_id": repo_id,
        "created_at": plan_data.get("created_at") or now,
        "updated_at": now,
        "status": status if status in PLAN_STATUSES else "active",
        "current_step_id": current_step_id,
        "steps": steps,
        "decision_log": list(plan_data.get("decision_log") or []),
        # Opt-in: let the Captain Watcher auto-dispatch the next queued step when the
        # current one completes cleanly (YOLO/unattended execution). Off by default —
        # the manual, gate-approved flow stays the default experience.
        "auto_advance": bool(plan_data.get("auto_advance", False)),
        # Measurable loop conditions (v2.6): a plan can carry a check command,
        # a dispatch budget, and file-scope constraints. Budget exhaustion or a
        # failing check halts the loop with a recorded blocker — never a silent retry.
        "check_command": str(plan_data.get("check_command") or "").strip() or None,
        "max_dispatches": max(0, int(plan_data.get("max_dispatches") or 0)),
        "dispatch_count": max(0, int(plan_data.get("dispatch_count") or 0)),
        "scope_paths": [str(p).strip() for p in (plan_data.get("scope_paths") or []) if str(p).strip()],
        "blocker": plan_data.get("blocker"),
        # Execution location is a property of the shared Mission contract. A
        # cloud operation is an allowlisted capability name, never a command.
        "execution_target": str(plan_data.get("execution_target") or "auto"),
        "cloud_operation": plan_data.get("cloud_operation"),
    }
    if not record["decision_log"]:
        append_decision_log(record, action="plan_created", detail="Captain plan persisted.", step_id=current_step_id)
    with _FILE_LOCK:
        path = plans_index_path(root)
        rows = _read_plans(path)
        rows = [row for row in rows if row.get("plan_id") != plan_id]
        rows.insert(0, record)
        _write_plans(path, rows[:100])
    _sync_cloud_plan(record)
    return sanitize_plan_detail(record)


def _save_plan(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    plan["updated_at"] = _now_iso()
    with _FILE_LOCK:
        path = plans_index_path(root)
        rows = _read_plans(path)
        found = False
        for index, row in enumerate(rows):
            if row.get("plan_id") == plan.get("plan_id"):
                rows[index] = plan
                found = True
                break
        if not found:
            rows.insert(0, plan)
        _write_plans(path, rows[:100])
    _sync_cloud_plan(plan)
    return plan


def get_plan_record(root: Path, plan_id: str) -> dict[str, Any] | None:
    cloud_plan = _cloud_plan(plan_id)
    if cloud_plan is not None:
        return cloud_plan
    with _FILE_LOCK:
        rows = _read_plans(plans_index_path(root))
    for row in rows:
        if row.get("plan_id") == plan_id:
            return row
    return None


def list_recent_plans(root: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    plane = _cloud_plane()
    if plane is not None:
        try:
            cloud_plans = plane.list_records("mission_plan", limit=limit)
            if cloud_plans:
                return [sanitize_plan_summary(row) for row in cloud_plans]
        except Exception:
            pass
    with _FILE_LOCK:
        rows = _read_plans(plans_index_path(root))
    return [sanitize_plan_summary(row) for row in rows[:limit]]


def get_plan_detail(root: Path, plan_id: str, *, include_prompts: bool = True) -> dict[str, Any] | None:
    plan = get_plan_record(root, plan_id)
    if plan is None:
        return None
    if include_prompts:
        return sanitize_plan_detail(plan)
    return sanitize_plan_summary(plan)


def mark_step_dispatched(
    root: Path,
    plan_id: str,
    step_id: str,
    *,
    run_id: str,
    status: str = "dispatched",
) -> dict[str, Any]:
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    if plan.get("status") != "active":
        raise HTTPException(status_code=409, detail="Captain plan is not active.")
    step = _find_step(plan, step_id)
    if plan.get("current_step_id") != step_id:
        raise HTTPException(status_code=409, detail="Only the current Captain step can be dispatched.")
    if step.get("status") not in DISPATCHABLE_STEP_STATUSES:
        raise HTTPException(status_code=409, detail=f"Step cannot be dispatched from status {step.get('status')}.")
    step["status"] = status
    step["run_id"] = run_id
    step["updated_at"] = _now_iso()
    append_decision_log(plan, action="step_dispatched", detail=f"Dispatched step to Codex run {run_id}.", step_id=step_id)
    saved = _save_plan(root, plan)
    return sanitize_plan_detail(saved)


def mark_step_running(root: Path, plan_id: str, step_id: str) -> dict[str, Any] | None:
    plan = get_plan_record(root, plan_id)
    if plan is None:
        return None
    step = _find_step(plan, step_id)
    if step.get("status") in {"dispatched", "queued", "revised"}:
        step["status"] = "running"
        step["updated_at"] = _now_iso()
        return sanitize_plan_detail(_save_plan(root, plan))
    return sanitize_plan_detail(plan)


def complete_step(
    root: Path,
    plan_id: str,
    step_id: str,
    *,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    if plan.get("status") != "active":
        raise HTTPException(status_code=409, detail="Captain plan is not active.")
    step = _find_step(plan, step_id)
    if plan.get("current_step_id") != step_id:
        raise HTTPException(status_code=409, detail="Only the current Captain step can be marked done.")
    if step.get("status") in {"passed", "skipped", "stopped"}:
        raise HTTPException(status_code=409, detail="Step is already complete.")
    if evidence_ids:
        merged = list(step.get("evidence_ids") or [])
        for evidence_id in evidence_ids:
            if evidence_id and evidence_id not in merged:
                merged.append(evidence_id)
        step["evidence_ids"] = merged
    step["status"] = "passed"
    step["updated_at"] = _now_iso()
    next_step_id = _next_queued_step_id(plan, step_id)
    if next_step_id:
        plan["current_step_id"] = next_step_id
        plan["status"] = "active"
    else:
        plan["status"] = "completed"
        plan["current_step_id"] = step_id
    append_decision_log(
        plan,
        action="step_completed",
        detail="Operator marked the current step done. Next step is ready but not auto-dispatched.",
        step_id=step_id,
    )
    saved = _save_plan(root, plan)
    return sanitize_plan_detail(saved)


def note_step_awaiting_gate_review(
    root: Path,
    plan_id: str,
    step_id: str,
    *,
    note: str,
) -> dict[str, Any]:
    """Log that the Captain Watcher observed a clean CLI exit for this step. Does NOT
    change step status or complete the step — a pending proof gate (created by the
    caller) still has to be approved by a human before `complete_step` can succeed
    (assert_step_completion_allowed enforces this). Auto-advance to the next step only
    happens after that gate is approved, not on watcher completion alone — see
    post_mcharness_gate_decision in api.py.
    """
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    append_decision_log(
        plan,
        action="step_awaiting_gate_review",
        detail=note,
        step_id=step_id,
    )
    saved = _save_plan(root, plan)
    return sanitize_plan_detail(saved)


def mark_step_needs_review(
    root: Path,
    plan_id: str,
    step_id: str,
    *,
    note: str,
) -> dict[str, Any]:
    """Mark the current step needs_review when the Captain Watcher detects a stalled or
    errored run. Stops auto-advance for this plan (needs_review is not auto-dispatched)
    and surfaces the reason in the decision log instead of retrying silently.
    """
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    step = _find_step(plan, step_id)
    step["status"] = "needs_review"
    step["updated_at"] = _now_iso()
    append_decision_log(
        plan,
        action="step_needs_review",
        detail=note,
        step_id=step_id,
    )
    saved = _save_plan(root, plan)
    return sanitize_plan_detail(saved)


def revise_step(
    root: Path,
    plan_id: str,
    step_id: str,
    *,
    title: str | None = None,
    prompt: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    if plan.get("status") != "active":
        raise HTTPException(status_code=409, detail="Captain plan is not active.")
    step = _find_step(plan, step_id)
    if title and title.strip():
        step["title"] = title.strip()
    if prompt and prompt.strip():
        step["prompt"] = prompt.strip()
    step["status"] = "revised"
    step["updated_at"] = _now_iso()
    append_decision_log(
        plan,
        action="step_revised",
        detail=note or "Operator revised the step prompt.",
        step_id=step_id,
    )
    saved = _save_plan(root, plan)
    return sanitize_plan_detail(saved)


def stop_plan(root: Path, plan_id: str, *, note: str | None = None) -> dict[str, Any]:
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    plan["status"] = "stopped"
    for step in plan.get("steps") or []:
        if step.get("status") in {"queued", "revised", "dispatched", "running", "needs_review"}:
            step["status"] = "stopped"
            step["updated_at"] = _now_iso()
    append_decision_log(plan, action="plan_stopped", detail=note or "Operator stopped the Captain plan.", step_id=plan.get("current_step_id"))
    saved = _save_plan(root, plan)
    return sanitize_plan_detail(saved)


def pause_mission_plan(root: Path, plan_id: str, *, note: str | None = None) -> dict[str, Any]:
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    plan["status"] = "stopped"
    for step in plan.get("steps") or []:
        if step.get("status") in {"queued", "revised", "dispatched", "running", "needs_review"}:
            step["status"] = "stopped"
            step["updated_at"] = _now_iso()
    append_decision_log(
        plan,
        action="mission_paused",
        detail=note or "Operator paused the mission.",
        step_id=plan.get("current_step_id"),
    )
    saved = _save_plan(root, plan)
    return sanitize_plan_detail(saved)


def request_plan_adjustment(
    root: Path,
    plan_id: str,
    *,
    note: str | None = None,
    adjustments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    detail = note or "Plan adjustment requested. Human review required before changes are applied."
    if adjustments:
        detail = f"{detail} Requested changes recorded for operator review."
    append_decision_log(
        plan,
        action="plan_adjustment_requested",
        detail=detail,
        step_id=plan.get("current_step_id"),
    )
    saved = _save_plan(root, plan)
    return sanitize_plan_detail(saved)


def increment_dispatch_count(root: Path, plan_id: str) -> int:
    """Count every dispatch attempt (including blocked ones) against the plan's
    budget (v2.6). Returns the new count."""
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    plan["dispatch_count"] = int(plan.get("dispatch_count") or 0) + 1
    _save_plan(root, plan)
    return int(plan["dispatch_count"])


def record_loop_blocker(root: Path, plan_id: str, *, reason: str, kind: str = "loop_blocked") -> dict[str, Any]:
    """Halt a plan with an explicit blocker report (v2.6). Stops the plan and all
    pending steps so nothing keeps looping, and surfaces the reason."""
    plan = get_plan_record(root, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    plan["blocker"] = {"kind": kind, "reason": reason, "at": _now_iso()}
    plan["status"] = "stopped"
    for step in plan.get("steps") or []:
        if step.get("status") in {"queued", "revised", "dispatched", "running", "needs_review"}:
            step["status"] = "stopped"
            step["updated_at"] = _now_iso()
    append_decision_log(plan, action=kind, detail=reason, step_id=plan.get("current_step_id"))
    saved = _save_plan(root, plan)
    return sanitize_plan_detail(saved)


def sanitize_plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    steps = _sorted_steps(plan.get("steps") or [])
    return {
        "plan_id": plan.get("plan_id"),
        "goal": plan.get("goal"),
        "title": plan.get("title"),
        "summary": plan.get("summary"),
        "repo_id": plan.get("repo_id"),
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
        "status": plan.get("status"),
        "current_step_id": plan.get("current_step_id"),
        "auto_advance": bool(plan.get("auto_advance", False)),
        "check_command": plan.get("check_command"),
        "max_dispatches": int(plan.get("max_dispatches") or 0),
        "dispatch_count": int(plan.get("dispatch_count") or 0),
        "scope_paths": list(plan.get("scope_paths") or []),
        "blocker": plan.get("blocker"),
        "execution_target": plan.get("execution_target", "auto"),
        "cloud_operation": plan.get("cloud_operation"),
        "step_count": len(steps),
        "steps": [
            {
                "step_id": step.get("step_id"),
                "order": step.get("order"),
                "title": step.get("title"),
                "agent_id": step.get("agent_id"),
                "status": step.get("status"),
                "prompt_preview": _prompt_preview(step.get("prompt") or "", 160),
                "run_id": step.get("run_id"),
                "evidence_count": len(step.get("evidence_ids") or []),
                "evidence_ids": list(step.get("evidence_ids") or []),
            }
            for step in steps
        ],
    }


def sanitize_plan_detail(plan: dict[str, Any], *, include_prompts: bool = True) -> dict[str, Any]:
    summary = sanitize_plan_summary(plan)
    if include_prompts:
        step_map = {str(step.get("step_id")): step for step in _sorted_steps(plan.get("steps") or [])}
        summary["steps"] = [
            {
                **step_summary,
                "prompt": str(step_map.get(str(step_summary.get("step_id")), {}).get("prompt") or ""),
            }
            for step_summary in summary["steps"]
        ]
    summary["decision_log"] = list(plan.get("decision_log") or [])[:20]
    return summary


def sanitize_plan_public(plan: dict[str, Any]) -> dict[str, Any]:
    summary = sanitize_plan_summary(plan)
    for step in summary.get("steps") or []:
        step.pop("evidence_ids", None)
    return summary
