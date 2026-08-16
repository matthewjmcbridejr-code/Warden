"""Unit tests for EnforcementAdapter policy enforcement."""
from __future__ import annotations

from src.warden.enforcement_adapter import EnforcementAdapter
from src.warden.policy_engine import PolicyEngine
from src.warden.capability_grants import ControlPlaneStore


def test_enforcement_adapter_grant_matching_and_ask(tmp_path):
    store = ControlPlaneStore(store_path=tmp_path / "control.json")
    adapter = EnforcementAdapter(store=store)

    # 1. READ tool call -> ALLOW
    dec1, grant1 = adapter.evaluate_tool_call("warden_health", risk_class="READ")
    assert dec1.verdict == "ALLOW"
    assert grant1 is None

    # 2. DESTRUCTIVE tool call -> ASK (creates approval)
    dec2, grant2 = adapter.evaluate_tool_call("warden_cancel_task", arguments={"task_id": "tsk_demo"}, risk_class="DESTRUCTIVE")
    assert dec2.verdict == "ASK"
    assert dec2.approval_request_id is not None
    assert grant2 is None

    # 3. Operator approves approval request -> issues grant
    app_res, issued_grant = store.resolve_approval(dec2.approval_request_id, verdict="approved", resolver_identity="operator")
    assert issued_grant is not None

    # 4. Same tool call retried -> matches grant and ALLOWs!
    dec3, grant3 = adapter.evaluate_tool_call("warden_cancel_task", arguments={"task_id": "tsk_demo"}, risk_class="DESTRUCTIVE")
    assert dec3.verdict == "ALLOW"
    assert dec3.reason_code == "grant_matched"
    assert grant3.grant_id == issued_grant.grant_id
