"""Unit tests for PolicyEngine and policy revisioning."""
from __future__ import annotations

from src.warden.action_model import WardenActionV1
from src.warden.policy_engine import PolicyEngine, compute_policy_revision, DEFAULT_POLICY_RULES, PolicyRule


def test_policy_revision_stability():
    rev1 = compute_policy_revision(DEFAULT_POLICY_RULES)
    assert rev1.startswith("pol_")

    rev2 = compute_policy_revision(DEFAULT_POLICY_RULES)
    assert rev1 == rev2


def test_policy_engine_verdicts():
    engine = PolicyEngine()

    # 1. READ action -> ALLOW
    read_action = WardenActionV1.create("warden_health", risk_class="READ")
    read_dec = engine.evaluate(read_action)
    assert read_dec.verdict == "ALLOW"
    assert read_dec.reason_code == "read_only_allowed"

    # 2. Self approval action -> DENY
    self_app_action = WardenActionV1.create("warden_approve_myself", risk_class="DESTRUCTIVE")
    self_app_dec = engine.evaluate(self_app_action)
    assert self_app_dec.verdict == "DENY"
    assert self_app_dec.reason_code == "self_approval_prohibited"

    # 3. Destructive action -> ASK
    dest_action = WardenActionV1.create("warden_cancel_task", risk_class="DESTRUCTIVE")
    dest_dec = engine.evaluate(dest_action)
    assert dest_dec.verdict == "ASK"
    assert dest_dec.capability_grant_required is True
    assert dest_dec.reason_code == "operator_approval_required"
