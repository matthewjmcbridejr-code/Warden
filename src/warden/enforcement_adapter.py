"""Warden Enforcement Adapter for Warden Control Plane v1.

Intercepts execution requests, evaluates policy decisions, matches active capability grants,
enforces authorization verdicts, and emits operational evidence.
"""

from __future__ import annotations

from typing import Any
from src.warden.action_model import WardenActionV1, PrincipalIdentity, RiskClass
from src.warden.decision_model import WardenDecisionV1
from src.warden.policy_engine import PolicyEngine
from src.warden.capability_grants import ControlPlaneStore, CapabilityGrant


class EnforcementAdapter:
    def __init__(self, policy_engine: PolicyEngine | None = None, store: ControlPlaneStore | None = None) -> None:
        self.policy_engine = policy_engine or PolicyEngine()
        self.store = store or ControlPlaneStore()

    def evaluate_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        project: str = "warden",
        principal: PrincipalIdentity | None = None,
        risk_class: RiskClass = "LOW_WRITE",
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> tuple[WardenDecisionV1, CapabilityGrant | None]:
        """Evaluates a tool call through grant matching and policy evaluation."""
        action = WardenActionV1.create(
            tool_name=tool_name,
            arguments=arguments,
            project=project,
            principal=principal,
            risk_class=risk_class,
            task_id=task_id,
            run_id=run_id,
        )

        # 1. Automatic Grant Matching
        matching_grant = self.store.find_matching_grant(action)
        if matching_grant:
            self.store.consume_grant(matching_grant.grant_id)
            decision = WardenDecisionV1(
                action_id=action.action_id,
                verdict="ALLOW",
                reason_code="grant_matched",
                reason=f"Action authorized under active Capability Grant {matching_grant.grant_id}.",
                policy_revision=self.policy_engine.policy_revision,
                evidence_refs=[f"warden://grants/{matching_grant.grant_id}"],
            )
            return decision, matching_grant

        # 2. Policy Engine Evaluation
        decision = self.policy_engine.evaluate(action)

        # 3. Handle ASK verdict -> create ApprovalRequest
        if decision.verdict == "ASK":
            approval = self.store.create_approval(action, decision)
            decision.approval_request_id = approval.approval_id

        return decision, None
