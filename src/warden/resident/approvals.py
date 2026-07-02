"""Approval queue for risky resident actions.

Anything that would send email, change DNS, deploy production, stop/run an
agent, or touch a file goes through this queue rather than executing
directly. Approve/deny are operator (Matt) actions; execute() only runs
when a safe executor exists for the action_type — otherwise it returns a
dry-run "executor not implemented" response, same policy as warden_client.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

ACTION_TYPES = (
    "email_send", "dns_change", "production_deploy", "agent_stop",
    "agent_run", "file_change", "other",
)
RISK_LEVELS = ("low", "medium", "high")
STATUSES = ("pending", "approved", "denied", "expired", "executed", "failed")

DEFAULT_EXPIRY_HOURS = 24

_SECRET_LIKE_KEYS = ("token", "api_key", "secret", "password", "auth", "cookie")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, dict):
            out[k] = _redact_payload(v)
        elif any(s in k.lower() for s in _SECRET_LIKE_KEYS):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


@dataclass
class Approval:
    approval_id: str
    source: str
    action_type: str
    summary: str
    risk_level: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: str = field(default_factory=lambda: _now().isoformat())
    expires_at: str = field(default_factory=lambda: (_now() + timedelta(hours=DEFAULT_EXPIRY_HOURS)).isoformat())
    created_by: str = "resident"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Approval":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def is_expired(self) -> bool:
        return _now() > datetime.fromisoformat(self.expires_at)


# Executors registered by action_type. None means "no safe executor exists" —
# execute() will return a dry-run response for that action_type.
_EXECUTORS: dict[str, Callable[[Approval], dict]] = {}


def register_executor(action_type: str, fn: Callable[[Approval], dict]) -> None:
    _EXECUTORS[action_type] = fn


class ApprovalQueue:
    def __init__(self, state) -> None:
        self.state = state

    def create(
        self,
        source: str,
        action_type: str,
        summary: str,
        risk_level: str = "medium",
        payload: Optional[dict[str, Any]] = None,
        created_by: str = "resident",
        expiry_hours: int = DEFAULT_EXPIRY_HOURS,
    ) -> Approval:
        if action_type not in ACTION_TYPES:
            raise ValueError(f"unknown action_type: {action_type}")
        if risk_level not in RISK_LEVELS:
            raise ValueError(f"unknown risk_level: {risk_level}")
        approval = Approval(
            approval_id=uuid.uuid4().hex[:10],
            source=source,
            action_type=action_type,
            summary=summary,
            risk_level=risk_level,
            payload=_redact_payload(payload or {}),
            created_by=created_by,
            expires_at=(_now() + timedelta(hours=expiry_hours)).isoformat(),
        )
        self.state.save_approval(approval.approval_id, approval.to_dict())
        self.state.audit("approval_created", {"approval_id": approval.approval_id, "action_type": action_type})
        return approval

    def get(self, approval_id: str) -> Optional[Approval]:
        data = self.state.get_approval(approval_id)
        if data is None:
            return None
        approval = Approval.from_dict(data)
        if approval.status == "pending" and approval.is_expired():
            approval.status = "expired"
            self.state.save_approval(approval.approval_id, approval.to_dict())
        return approval

    def list(self, status: Optional[str] = None) -> list[Approval]:
        items = []
        for d in self.state.list_approvals():
            approval = Approval.from_dict(d)
            if approval.status == "pending" and approval.is_expired():
                approval.status = "expired"
                self.state.save_approval(approval.approval_id, approval.to_dict())
            items.append(approval)
        if status:
            items = [a for a in items if a.status == status]
        return items

    def approve(self, approval_id: str) -> Optional[Approval]:
        approval = self.get(approval_id)
        if approval is None or approval.status != "pending":
            return approval
        approval.status = "approved"
        self.state.save_approval(approval.approval_id, approval.to_dict())
        self.state.audit("approval_approved", {"approval_id": approval_id})
        return approval

    def deny(self, approval_id: str) -> Optional[Approval]:
        approval = self.get(approval_id)
        if approval is None or approval.status != "pending":
            return approval
        approval.status = "denied"
        self.state.save_approval(approval.approval_id, approval.to_dict())
        self.state.audit("approval_denied", {"approval_id": approval_id})
        return approval

    def execute(self, approval_id: str) -> dict:
        """Execute an approved action if a safe executor is registered for its
        action_type; otherwise return a dry-run 'executor not implemented' response."""
        approval = self.get(approval_id)
        if approval is None:
            return {"ok": False, "short_summary": f"No approval {approval_id!r} found.", "key_fields": {}}
        if approval.status != "approved":
            return {
                "ok": False,
                "short_summary": f"Approval {approval_id} is {approval.status}, not approved.",
                "key_fields": {"status": approval.status},
            }
        executor = _EXECUTORS.get(approval.action_type)
        if executor is None:
            return {
                "ok": False,
                "short_summary": f"executor not implemented for action_type={approval.action_type!r}. Dry-run only.",
                "key_fields": {"approval_id": approval_id, "dry_run": True},
            }
        try:
            result = executor(approval)
            approval.status = "executed" if result.get("ok") else "failed"
            self.state.save_approval(approval.approval_id, approval.to_dict())
            self.state.audit("approval_executed", {"approval_id": approval_id, "ok": result.get("ok")})
            return result
        except Exception as exc:
            approval.status = "failed"
            self.state.save_approval(approval.approval_id, approval.to_dict())
            return {"ok": False, "short_summary": f"Execution failed: {exc}", "key_fields": {}}
