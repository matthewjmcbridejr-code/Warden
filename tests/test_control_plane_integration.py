"""End-to-End Integration & Security Proofs for Warden Control Plane v1."""
from __future__ import annotations

import pytest
from src.warden.action_model import WardenActionV1
from src.warden.decision_model import WardenDecisionV1
from src.warden.policy_engine import PolicyEngine
from src.warden.capability_grants import ControlPlaneStore
from src.warden.enforcement_adapter import EnforcementAdapter


def test_e2e_control_plane_lifecycle_and_security_proofs(tmp_path):
    import src.warden.capability_grants
    src.warden.capability_grants.DEFAULT_CONTROL_PLANE_PATH = tmp_path / "control.json"

    store = ControlPlaneStore(store_path=tmp_path / "control.json")
    adapter = EnforcementAdapter(store=store)

    # 1. Consequential Action on Demo Task
    task_id = "control-plane-live-proof-101"
    action = WardenActionV1.create(
        tool_name="warden_cancel_task",
        arguments={"task_id": task_id, "reason": "superseded by decision"},
        project="warden",
        risk_class="DESTRUCTIVE",
        task_id=task_id,
    )

    # 2. EnforcementAdapter evaluates action -> returns ASK + creates pending approval
    dec, grant = adapter.evaluate_tool_call(
        tool_name=action.action.tool_name,
        arguments=action.safe_argument_summary,
        project=action.project,
        risk_class=action.risk.risk_class,
        task_id=action.task_id,
    )
    assert dec.verdict == "ASK"
    assert dec.approval_request_id is not None
    assert grant is None

    # 3. Verify approval in pending list
    pending = store.list_pending_approvals()
    assert len(pending) == 1
    assert pending[0].approval_id == dec.approval_request_id

    # 4. Self-approval attempt by agent MUST FAIL
    with pytest.raises(ValueError, match="AUTHORITY SEPARATION VIOLATION"):
        store.resolve_approval(dec.approval_request_id, verdict="approved", resolver_identity="agent_bot", is_agent=True)

    # 5. Operator approves approval request -> issues grant
    app_res, issued_grant = store.resolve_approval(dec.approval_request_id, verdict="approved", resolver_identity="operator", is_agent=False)
    assert app_res.status == "approved"
    assert issued_grant is not None
    assert issued_grant.status == "active"

    # 6. Retry exact same action -> matches grant and ALLOWs!
    dec_retry, grant_used = adapter.evaluate_tool_call(
        tool_name=action.action.tool_name,
        arguments=action.safe_argument_summary,
        project=action.project,
        risk_class=action.risk.risk_class,
        task_id=action.task_id,
    )
    assert dec_retry.verdict == "ALLOW"
    assert dec_retry.reason_code == "grant_matched"

    # 7. Grant is now consumed
    assert grant_used.status == "consumed"

    # 8. Mutated Action Retry -> old grant does NOT authorize B!
    mutated_dec, mutated_grant = adapter.evaluate_tool_call(
        tool_name="warden_cancel_task",
        arguments={"task_id": "different_task_id"},
        project="warden",
        risk_class="DESTRUCTIVE",
    )
    assert mutated_dec.verdict == "ASK"
    assert mutated_grant is None

    # 9. Task Supersedence Revokes Grants
    grt_task = store.issue_grant_for_action(action, decision_id="dec_task", max_uses=1)
    assert grt_task.status == "active"
    store.revoke_grants_for_task(task_id)
    assert grt_task.status == "revoked"
    assert grt_task.is_valid_for(action) is False
