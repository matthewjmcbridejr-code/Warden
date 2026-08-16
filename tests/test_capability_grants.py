from pathlib import Path
from src.warden.action_model import WardenActionV1
from src.warden.decision_model import WardenDecisionV1
from src.warden.capability_grants import ControlPlaneStore, CapabilityGrant, ApprovalRequest


def test_agent_self_approval_denied(tmp_path):
    import pytest
    store = ControlPlaneStore(store_path=tmp_path / "control.json")

    action = WardenActionV1.create("warden_cancel_task", risk_class="DESTRUCTIVE")
    decision = WardenDecisionV1(action_id=action.action_id, verdict="ASK")

    approval = store.create_approval(action, decision)

    # Attempt self-approval by agent -> MUST raise ValueError
    with pytest.raises(ValueError, match="AUTHORITY SEPARATION VIOLATION"):
        store.resolve_approval(approval.approval_id, verdict="approved", resolver_identity="agent_xyz", is_agent=True)

    assert approval.status == "pending"


def test_operator_approval_issues_grant(tmp_path):
    store = ControlPlaneStore(store_path=tmp_path / "control.json")

    action = WardenActionV1.create("warden_cancel_task", risk_class="DESTRUCTIVE")
    decision = WardenDecisionV1(action_id=action.action_id, verdict="ASK")

    approval = store.create_approval(action, decision)
    app_res, grant = store.resolve_approval(approval.approval_id, verdict="approved", resolver_identity="operator", is_agent=False)

    assert app_res.status == "approved"
    assert grant is not None
    assert grant.status == "active"
    assert grant.issued_by == "operator"


def test_exact_action_fingerprint_binding(tmp_path):
    store = ControlPlaneStore(store_path=tmp_path / "control.json")

    action1 = WardenActionV1.create("warden_cancel_task", arguments={"task_id": "tsk_123"}, risk_class="DESTRUCTIVE")
    grant = store.issue_grant_for_action(action1, decision_id="dec_1", max_uses=1)

    # Action 1 matches grant
    assert grant.is_valid_for(action1) is True

    # Mutated Action 2 with different argument fingerprint does NOT match grant!
    action2_mutated = WardenActionV1.create("warden_cancel_task", arguments={"task_id": "tsk_999"}, risk_class="DESTRUCTIVE")
    assert grant.is_valid_for(action2_mutated) is False


def test_task_invalidation_revokes_grant(tmp_path):
    store = ControlPlaneStore(store_path=tmp_path / "control.json")

    action = WardenActionV1.create("warden_cancel_task", task_id="tsk_demo_01", risk_class="DESTRUCTIVE")
    grant = store.issue_grant_for_action(action, decision_id="dec_1", max_uses=1)

    assert grant.status == "active"

    # Task superseded/cancelled -> revoke linked grants
    revoked = store.revoke_grants_for_task("tsk_demo_01")
    assert grant.grant_id in revoked
    assert grant.status == "revoked"
    assert grant.is_valid_for(action) is False
