"""Warden Capability Grants & Out-of-Band Approval Broker for Warden Control Plane v1.

Manages scoped capability grants, out-of-band operator approval requests,
strict authority separation (agents cannot self-approve), exact action fingerprint binding,
and task invalidation revocation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

from src.warden.action_model import WardenActionV1
from src.warden.decision_model import WardenDecisionV1

GrantStatus = Literal["active", "consumed", "revoked", "expired"]
ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]


class CapabilityGrant(BaseModel):
    grant_id: str = Field(default_factory=lambda: f"grt_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
    agent_id: str = "operator"
    session_id: str = "session_default"
    capabilities: list[str] = Field(default_factory=list)
    action_pattern: str = "*"
    resource: str = "warden"
    project: str = "warden"
    task_id: str | None = None
    run_id: str | None = None
    decision_id: str = ""
    approval_id: str | None = None
    action_fingerprint: str = ""
    max_uses: int = 1
    uses: int = 0
    status: GrantStatus = "active"
    issued_by: str = "operator"
    policy_revision: str = "pol_default_v1"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = Field(
        default_factory=lambda: (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    )

    def is_valid_for(self, action: WardenActionV1) -> bool:
        if self.status != "active":
            return False
        if self.uses >= self.max_uses:
            return False
        # Expiry check
        try:
            exp = datetime.fromisoformat(self.expires_at)
            if datetime.now(timezone.utc) > exp:
                return False
        except Exception:
            pass

        # Principal check
        if self.agent_id != action.principal.agent_id:
            return False

        # Action fingerprint binding check
        if self.action_fingerprint and self.action_fingerprint != action.argument_fingerprint:
            return False

        return True


class ApprovalRequest(BaseModel):
    approval_id: str = Field(default_factory=lambda: f"app_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
    action_id: str
    decision_id: str
    agent_id: str = "operator"
    session_id: str = "session_default"
    summary: str
    risk_class: str = "LOW_WRITE"
    resource: str = "warden"
    project: str = "warden"
    reason: str
    status: ApprovalStatus = "pending"
    resulting_grant_id: str | None = None
    requested_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = Field(
        default_factory=lambda: (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    )
    resolved_by: str | None = None
    resolved_at: str | None = None


DEFAULT_CONTROL_PLANE_PATH = Path.home() / ".config" / "warden-brain" / "control_plane.json"


class ControlPlaneStore:
    def __init__(self, store_path: Path | None = None) -> None:
        self._path = store_path or DEFAULT_CONTROL_PLANE_PATH
        self._grants: dict[str, CapabilityGrant] = {}
        self._approvals: dict[str, ApprovalRequest] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for g in data.get("grants", []):
                grant = CapabilityGrant(**g)
                self._grants[grant.grant_id] = grant
            for a in data.get("approvals", []):
                approval = ApprovalRequest(**a)
                self._approvals[approval.approval_id] = approval
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "grants": [g.model_dump(mode="json") for g in self._grants.values()],
                "approvals": [a.model_dump(mode="json") for a in self._approvals.values()],
            }
            self._path.write_text(json.dumps(payload, indent=2))
        except Exception:
            pass

    def create_approval(self, action: WardenActionV1, decision: WardenDecisionV1) -> ApprovalRequest:
        approval = ApprovalRequest(
            action_id=action.action_id,
            decision_id=decision.decision_id,
            agent_id=action.principal.agent_id,
            session_id=action.principal.session_id,
            summary=f"Approval requested for tool {action.action.tool_name or 'action'}",
            risk_class=action.risk.risk_class,
            resource=action.resource.id,
            project=action.project,
            reason=decision.reason,
        )
        self._approvals[approval.approval_id] = approval
        self._save()
        return approval

    def list_pending_approvals(self) -> list[ApprovalRequest]:
        return [a for a in self._approvals.values() if a.status == "pending"]

    def list_active_grants(self) -> list[CapabilityGrant]:
        return [g for g in self._grants.values() if g.status == "active"]

    def resolve_approval(
        self,
        approval_id: str,
        verdict: Literal["approved", "rejected"],
        resolver_identity: str = "operator",
        is_agent: bool = False,
    ) -> tuple[ApprovalRequest, CapabilityGrant | None]:
        """Resolves an approval request. Enforces STRICT AUTHORITY SEPARATION (agents cannot self-approve)."""
        if is_agent or resolver_identity.startswith("agent"):
            raise ValueError("AUTHORITY SEPARATION VIOLATION: Agents are not authorized to resolve approval requests!")

        approval = self._approvals.get(approval_id)
        if not approval:
            raise KeyError(f"Approval request {approval_id} not found.")

        if approval.status != "pending":
            raise ValueError(f"Approval request {approval_id} is already {approval.status}.")

        approval.status = verdict
        approval.resolved_by = resolver_identity
        approval.resolved_at = datetime.now(timezone.utc).isoformat()

        grant: CapabilityGrant | None = None
        if verdict == "approved":
            grant = CapabilityGrant(
                agent_id=approval.agent_id,
                session_id=approval.session_id,
                capabilities=[f"risk:{approval.risk_class}"],
                action_pattern="*",
                resource=approval.resource,
                project=approval.project,
                decision_id=approval.decision_id,
                approval_id=approval.approval_id,
                action_fingerprint="", # can bind to exact action fingerprint if available
                max_uses=1,
                issued_by=resolver_identity,
            )
            self._grants[grant.grant_id] = grant
            approval.resulting_grant_id = grant.grant_id

        self._save()
        return approval, grant

    def issue_grant_for_action(
        self,
        action: WardenActionV1,
        decision_id: str,
        approval_id: str | None = None,
        issuer: str = "operator",
        max_uses: int = 1,
    ) -> CapabilityGrant:
        grant = CapabilityGrant(
            agent_id=action.principal.agent_id,
            session_id=action.principal.session_id,
            capabilities=action.requested_capabilities,
            action_pattern=action.action.tool_name or "*",
            resource=action.resource.id,
            project=action.project,
            task_id=action.task_id,
            run_id=action.run_id,
            decision_id=decision_id,
            approval_id=approval_id,
            action_fingerprint=action.argument_fingerprint,
            max_uses=max_uses,
            issued_by=issuer,
        )
        self._grants[grant.grant_id] = grant
        self._save()
        return grant

    def find_matching_grant(self, action: WardenActionV1) -> CapabilityGrant | None:
        for grant in self._grants.values():
            if grant.is_valid_for(action):
                return grant
        return None

    def consume_grant(self, grant_id: str) -> CapabilityGrant:
        grant = self._grants.get(grant_id)
        if not grant:
            raise KeyError(f"Grant {grant_id} not found.")
        grant.uses += 1
        if grant.uses >= grant.max_uses:
            grant.status = "consumed"
        self._save()
        return grant

    def revoke_grants_for_task(self, task_id: str) -> list[str]:
        revoked_ids = []
        for grant in self._grants.values():
            if grant.task_id == task_id and grant.status == "active":
                grant.status = "revoked"
                revoked_ids.append(grant.grant_id)
        if revoked_ids:
            self._save()
        return revoked_ids
