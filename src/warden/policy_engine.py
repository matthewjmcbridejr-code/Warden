"""Warden Policy Engine & Policy Revision for Warden Control Plane v1.

Evaluates canonical WardenActionV1 operations against declarative policy rules,
producing deterministic WardenDecisionV1 verdicts and policy_revision hashes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from pydantic import BaseModel, Field

from src.warden.action_model import WardenActionV1, RiskClass
from src.warden.decision_model import WardenDecisionV1, Verdict, DecisionRemediation, AuthorizationConstraints


class PolicyRule(BaseModel):
    rule_id: str
    description: str = ""
    enabled: bool = True
    priority: int = 100 # lower number = higher priority
    principals: list[str] = Field(default_factory=lambda: ["*"])
    sources: list[str] = Field(default_factory=lambda: ["*"])
    tool_names: list[str] = Field(default_factory=lambda: ["*"])
    risk_classes: list[RiskClass | str] = Field(default_factory=lambda: ["*"])
    verdict: Verdict = "ALLOW"
    reason_code: str = "matched_rule"
    reason: str = ""
    capability_grant_required: bool = False
    safe_alternative: str | None = None


def compute_policy_revision(rules: list[PolicyRule]) -> str:
    """Computes a deterministic hash of active policy rules.

    Must ONLY change when active effective rules or rule parameters change.
    """
    active_rules = sorted(
        [r.model_dump(mode="json") for r in rules if r.enabled],
        key=lambda r: (r["priority"], r["rule_id"]),
    )
    payload = json.dumps(active_rules, sort_keys=True)
    return "pol_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


DEFAULT_POLICY_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="rule_self_approve_deny",
        description="Agents cannot approve their own authorization requests.",
        priority=10,
        tool_names=["warden_approve_myself", "approval_resolve", "resolve_approval"],
        verdict="DENY",
        reason_code="self_approval_prohibited",
        reason="Agents are strictly prohibited from resolving or approving their own authorization requests.",
    ),
    PolicyRule(
        rule_id="rule_destructive_ask",
        description="High-risk destructive or credential operations require operator approval.",
        priority=20,
        risk_classes=["DESTRUCTIVE", "CREDENTIAL", "SECURITY_SENSITIVE"],
        verdict="ASK",
        reason_code="operator_approval_required",
        reason="Operation is classified as high-risk and requires explicit operator authorization.",
        capability_grant_required=True,
    ),
    PolicyRule(
        rule_id="rule_read_allow",
        description="Read-only informational operations are allowed by default.",
        priority=30,
        risk_classes=["READ"],
        verdict="ALLOW",
        reason_code="read_only_allowed",
        reason="Read-only operation permitted.",
    ),
    PolicyRule(
        rule_id="rule_default_write_allow",
        description="Standard low-risk write operations allowed under default policy.",
        priority=50,
        risk_classes=["LOW_WRITE", "EXTERNAL_WRITE"],
        verdict="ALLOW",
        reason_code="standard_write_allowed",
        reason="Standard low-risk operation permitted.",
    ),
]


class PolicyEngine:
    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self.rules = rules if rules is not None else list(DEFAULT_POLICY_RULES)

    @property
    def policy_revision(self) -> str:
        return compute_policy_revision(self.rules)

    def evaluate(self, action: WardenActionV1) -> WardenDecisionV1:
        """Evaluates an action against sorted active rules, returning WardenDecisionV1."""
        sorted_rules = sorted(
            [r for r in self.rules if r.enabled],
            key=lambda r: (r.priority, r.rule_id),
        )

        matched_rule: PolicyRule | None = None
        for rule in sorted_rules:
            if not self._match_rule(rule, action):
                continue
            matched_rule = rule
            break

        if not matched_rule:
            matched_rule = PolicyRule(
                rule_id="rule_default_monitor",
                description="Default fallback rule.",
                verdict="MONITOR",
                reason_code="unmatched_action_monitored",
                reason="Action did not match specific rules; monitored by default.",
            )

        remediation = DecisionRemediation(
            safe_alternative=matched_rule.safe_alternative,
            operator_message=matched_rule.reason if matched_rule.verdict == "ASK" else None,
        )

        return WardenDecisionV1(
            action_id=action.action_id,
            verdict=matched_rule.verdict,
            reason_code=matched_rule.reason_code,
            reason=matched_rule.reason,
            matched_rules=[matched_rule.rule_id],
            policy_revision=self.policy_revision,
            decision_backend="builtin",
            evidence_refs=[f"warden://actions/{action.action_id}"],
            remediation=remediation,
            constraints=AuthorizationConstraints(resource_scope=action.project),
            capability_grant_required=matched_rule.capability_grant_required,
        )

    def _match_rule(self, rule: PolicyRule, action: WardenActionV1) -> bool:
        tool_name = action.action.tool_name or ""
        risk_class = action.risk.risk_class

        if "*" not in rule.principals and action.principal.agent_id not in rule.principals:
            return False
        if "*" not in rule.sources and action.source not in rule.sources:
            return False
        if "*" not in rule.tool_names and tool_name not in rule.tool_names:
            return False
        if "*" not in rule.risk_classes and risk_class not in rule.risk_classes:
            return False
        return True
