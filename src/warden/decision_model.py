"""Warden Decision Model (WardenDecisionV1) for Warden Control Plane v1.

Provides machine-readable policy verdicts (ALLOW, DENY, ASK, MONITOR),
remediation instructions, and authorization constraints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field

Verdict = Literal["ALLOW", "DENY", "ASK", "MONITOR"]


class DecisionRemediation(BaseModel):
    safe_alternative: str | None = None
    operator_message: str | None = None


class AuthorizationConstraints(BaseModel):
    expires_at: str | None = None
    max_uses: int = 1
    max_calls: int = 1
    allowed_paths: list[str] = Field(default_factory=list)
    network_targets: list[str] = Field(default_factory=list)
    branch: str | None = None
    head_sha: str | None = None
    resource_scope: str = "warden"
    max_cost_usd: float | None = None


class WardenDecisionV1(BaseModel):
    schema_version: str = "1.0.0"
    decision_id: str = Field(default_factory=lambda: f"dec_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
    action_id: str
    verdict: Verdict = "ALLOW"
    reason_code: str = "policy_allowed"
    reason: str = "Action allowed under active policy rules."
    matched_rules: list[str] = Field(default_factory=list)
    policy_revision: str = "pol_default_v1"
    decision_backend: str = "builtin"
    evidence_refs: list[str] = Field(default_factory=list)
    remediation: DecisionRemediation = Field(default_factory=DecisionRemediation)
    constraints: AuthorizationConstraints = Field(default_factory=AuthorizationConstraints)
    approval_request_id: str | None = None
    capability_grant_required: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
