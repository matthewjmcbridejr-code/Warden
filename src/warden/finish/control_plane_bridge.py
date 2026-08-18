"""Control Plane v1 Integration for Warden Finish Subsystem.

Wraps Finish actions in WardenActionV1, evaluates policy rules via PolicyEngine,
checks CapabilityGrants, and enforces single-boundary publish approvals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone

from ..action_model import WardenActionV1, RiskClass, PrincipalIdentity
from ..policy_engine import PolicyEngine, PolicyRule, DEFAULT_POLICY_RULES
from ..capability_grants import ControlPlaneStore
from ..decision_model import WardenDecisionV1
from .models import ActionRecord, ApprovalRecord, FinishJob


# Custom policy rules for Finish pipeline
FINISH_POLICY_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="rule_finish_auto_inspect_build",
        description="Local inspection, build, repair, and preview deploys are auto-approved under job scope.",
        priority=30,
        tool_names=[
            "finish_inspect",
            "finish_build",
            "finish_repair_build",
            "finish_provision_auth",
            "finish_provision_database",
            "finish_provision_storage",
            "finish_configure_env",
            "finish_deploy_preview",
            "finish_verify_preview",
        ],
        verdict="ALLOW",
        reason_code="finish_job_scope_allowed",
        reason="Local execution and preview operations fall within the active FinishJob scope.",
    ),
    PolicyRule(
        rule_id="rule_finish_production_publish_ask",
        description="Production deployment promotion requires explicit operator publish approval.",
        priority=15,
        tool_names=["finish_promote_production", "finish_dns_change"],
        verdict="ASK",
        reason_code="operator_publish_approval_required",
        reason="Promoting an application build to public production requires explicit operator approval.",
        capability_grant_required=True,
    ),
]


class FinishControlPlaneBridge:
    def __init__(self, store: Optional[ControlPlaneStore] = None):
        rules = list(DEFAULT_POLICY_RULES) + FINISH_POLICY_RULES
        self.policy_engine = PolicyEngine(rules=rules)
        store_path = Path.cwd() / "_mctable" / "finish" / "control_plane.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        self.cp_store = store or ControlPlaneStore(store_path=store_path)

    def evaluate_action(
        self,
        job: FinishJob,
        action_name: str,
        arguments: Dict[str, Any],
        risk_class: RiskClass = "LOW_WRITE",
    ) -> Tuple[WardenDecisionV1, Optional[ApprovalRecord]]:
        action = WardenActionV1.create(
            tool_name=action_name,
            arguments=arguments,
            project=job.project,
            risk_class=risk_class,
            run_id=job.job_id,
        )

        decision = self.policy_engine.evaluate(action)

        # Check existing capability grants if verdict is ASK
        if decision.verdict == "ASK":
            matching_grant = self.cp_store.find_matching_grant(action)
            if matching_grant:
                decision.verdict = "ALLOW"
                decision.reason = f"Allowed by existing capability grant {matching_grant.grant_id}"

        approval_rec: Optional[ApprovalRecord] = None
        if decision.verdict == "ASK":
            req = self.cp_store.create_approval(action, decision)
            approval_rec = ApprovalRecord(
                approval_id=req.approval_id,
                title=f"Promote {job.project} to Production",
                action_type=action_name,
                status="PENDING",
                detail=f"Operator approval required to publish {job.project} build to production.",
            )
            job.approvals.append(approval_rec)

        action_rec = ActionRecord(
            action_type=action_name,
            risk_class=risk_class,
            decision=decision.verdict,
            summary=f"Action '{action_name}' evaluated: {decision.verdict} ({decision.reason})",
        )
        job.actions.append(action_rec)

        return decision, approval_rec
