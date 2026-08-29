"""Manual proof gates for supervised operator review."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException

from .run_history import redact_secrets

_FILE_LOCK = threading.Lock()

GateStatus = Literal["pending", "approved", "blocked", "needs_more_evidence"]
GateDecision = Literal["approve", "block", "request_more_evidence"]

DECISION_STATUS: dict[str, GateStatus] = {
    "approve": "approved",
    "block": "blocked",
    "request_more_evidence": "needs_more_evidence",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cloud_plane():
    from .cloud_control_plane import CloudControlPlane, cloud_control_enabled
    return CloudControlPlane() if cloud_control_enabled() else None


def _sync_cloud_gate(gate: dict[str, Any]) -> None:
    plane = _cloud_plane()
    if plane is None:
        return
    try:
        plane.upsert_record("proof_gate", str(gate["gate_id"]), gate, source_updated_at=gate.get("decided_at") or gate.get("created_at"))
    except Exception:
        plane.enqueue_record("proof_gate", str(gate["gate_id"]), gate)


def _cloud_gate(gate_id: str) -> dict[str, Any] | None:
    plane = _cloud_plane()
    if plane is None:
        return None
    try:
        return plane.get_record("proof_gate", gate_id)
    except Exception:
        return None


def gates_index_path(root: Path) -> Path:
    return root / "gates" / "gates.json"


def _read_gates(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to read proof gates index.") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="Invalid proof gates index format.")
    return data


def _write_gates(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _sanitize_decision_entry(entry: dict[str, Any]) -> dict[str, Any]:
    reason, _ = redact_secrets(str(entry.get("reason") or ""))
    return {
        "at": entry.get("at"),
        "decision": entry.get("decision"),
        "decided_by": entry.get("decided_by"),
        "reason": reason or None,
    }


def _sanitize_gate(gate: dict[str, Any]) -> dict[str, Any]:
    title, _ = redact_secrets(str(gate.get("title") or ""))
    summary, _ = redact_secrets(str(gate.get("summary") or ""))
    reason, _ = redact_secrets(str(gate.get("decision_reason") or ""))
    decision_log = [
        _sanitize_decision_entry(entry)
        for entry in list(gate.get("decision_log") or [])
        if isinstance(entry, dict)
    ]
    return {
        "gate_id": gate.get("gate_id"),
        "run_id": gate.get("run_id"),
        "plan_id": gate.get("plan_id"),
        "step_id": gate.get("step_id"),
        "gate_type": gate.get("gate_type"),
        "status": gate.get("status"),
        "title": title,
        "summary": summary,
        "evidence_ids": list(gate.get("evidence_ids") or []),
        "created_at": gate.get("created_at"),
        "decided_at": gate.get("decided_at"),
        "decided_by": gate.get("decided_by"),
        "decision_reason": reason or None,
        "decision_log": decision_log[:20],
    }


def create_proof_gate(
    root: Path,
    *,
    run_id: str | None,
    plan_id: str | None = None,
    step_id: str | None = None,
    gate_type: str = "manual_review",
    title: str,
    summary: str = "",
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    safe_title, _ = redact_secrets(title.strip())
    safe_summary, _ = redact_secrets(summary.strip())
    if not safe_title:
        raise HTTPException(status_code=400, detail="Proof gate title is required.")
    gate_id = f"gate_{uuid.uuid4().hex[:10]}"
    record = {
        "gate_id": gate_id,
        "run_id": run_id,
        "plan_id": plan_id,
        "step_id": step_id,
        "gate_type": gate_type,
        "status": "pending",
        "title": safe_title[:160],
        "summary": safe_summary[:500],
        "evidence_ids": list(evidence_ids or []),
        "created_at": _now_iso(),
        "decided_at": None,
        "decided_by": None,
        "decision_reason": None,
        "decision_log": [],
    }
    with _FILE_LOCK:
        path = gates_index_path(root)
        rows = _read_gates(path)
        rows.insert(0, record)
        _write_gates(path, rows[:500])
    _sync_cloud_gate(record)
    return _sanitize_gate(record)


def get_proof_gate(root: Path, gate_id: str) -> dict[str, Any] | None:
    cloud = _cloud_gate(gate_id)
    if cloud is not None:
        return _sanitize_gate(cloud)
    with _FILE_LOCK:
        rows = _read_gates(gates_index_path(root))
    for row in rows:
        if row.get("gate_id") == gate_id:
            return _sanitize_gate(row)
    return None


def list_gates_for_run(root: Path, run_id: str) -> list[dict[str, Any]]:
    plane = _cloud_plane()
    if plane is not None:
        try:
            cloud = plane.list_records("proof_gate", limit=500)
            if cloud:
                return [_sanitize_gate(row) for row in cloud if row.get("run_id") == run_id]
        except Exception:
            pass
    with _FILE_LOCK:
        rows = _read_gates(gates_index_path(root))
    return [_sanitize_gate(row) for row in rows if row.get("run_id") == run_id]


def list_recent_gates(root: Path, *, limit: int = 30) -> list[dict[str, Any]]:
    plane = _cloud_plane()
    if plane is not None:
        try:
            cloud = plane.list_records("proof_gate", limit=limit)
            if cloud:
                return [_sanitize_gate(row) for row in cloud]
        except Exception:
            pass
    with _FILE_LOCK:
        rows = _read_gates(gates_index_path(root))
    return [_sanitize_gate(row) for row in rows[:limit]]


GATE_UI_LABELS: dict[str, str] = {
    "none": "No gate",
    "pending": "Proof pending",
    "approved": "Approved",
    "needs_more_evidence": "Needs more evidence",
    "blocked": "Blocked",
}


def gate_ui_label(status: str | None) -> str:
    if not status:
        return GATE_UI_LABELS["none"]
    return GATE_UI_LABELS.get(str(status), str(status).replace("_", " ").title())


def completion_block_reason(gate_status: str | None) -> str | None:
    if gate_status == "pending":
        return "Cannot mark step done while a proof gate is pending."
    if gate_status == "blocked":
        return "Step is blocked by a proof gate. Resolve or revise before continuing."
    if gate_status == "needs_more_evidence":
        return "Step needs more evidence before it can be marked done."
    return None


def assert_step_completion_allowed(root: Path, run_id: str | None) -> None:
    if not run_id:
        return
    status = gate_status_summary_for_run(root, str(run_id))
    reason = completion_block_reason(status)
    if reason:
        raise HTTPException(status_code=409, detail=reason)


def gate_status_summary_for_run(root: Path, run_id: str) -> str | None:
    gates = list_gates_for_run(root, run_id)
    if not gates:
        return None
    if any(gate.get("status") == "blocked" for gate in gates):
        return "blocked"
    if any(gate.get("status") == "needs_more_evidence" for gate in gates):
        return "needs_more_evidence"
    if any(gate.get("status") == "pending" for gate in gates):
        return "pending"
    if all(gate.get("status") == "approved" for gate in gates):
        return "approved"
    return gates[0].get("status")


def decide_proof_gate(
    root: Path,
    gate_id: str,
    *,
    decision: GateDecision,
    decided_by: str,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    if decision in {"block", "request_more_evidence"} and not (decision_reason or "").strip():
        raise HTTPException(status_code=400, detail="A short reason is required for block or request more evidence.")
    safe_reason, _ = redact_secrets((decision_reason or "").strip())
    with _FILE_LOCK:
        path = gates_index_path(root)
        rows = _read_gates(path)
        updated: dict[str, Any] | None = None
        for index, row in enumerate(rows):
            if row.get("gate_id") != gate_id:
                continue
            if row.get("status") != "pending":
                raise HTTPException(status_code=409, detail="Proof gate has already been decided.")
            now = _now_iso()
            log = list(row.get("decision_log") or [])
            log.insert(
                0,
                {
                    "at": now,
                    "decision": decision,
                    "decided_by": decided_by,
                    "reason": safe_reason,
                },
            )
            row["status"] = DECISION_STATUS[decision]
            row["decided_at"] = now
            row["decided_by"] = decided_by
            row["decision_reason"] = safe_reason or None
            row["decision_log"] = log[:50]
            rows[index] = row
            updated = row
            break
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Proof gate not found: {gate_id}")
        _write_gates(path, rows)
    if updated is not None:
        _sync_cloud_gate(updated)
    return _sanitize_gate(updated)
