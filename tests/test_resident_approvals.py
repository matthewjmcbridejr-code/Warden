"""Approval queue tests: approve/deny/expire, execute-if-safe-executor."""
from datetime import datetime, timedelta, timezone

import pytest

from src.warden.resident.approvals import Approval, ApprovalQueue, register_executor
from src.warden.resident.state import ResidentState


@pytest.fixture
def queue(tmp_path):
    state = ResidentState(str(tmp_path / "resident.sqlite"))
    return ApprovalQueue(state)


def test_create_approval(queue):
    approval = queue.create(source="test", action_type="email_send", summary="send X", risk_level="medium")
    assert approval.status == "pending"
    assert approval.approval_id


def test_create_invalid_action_type_raises(queue):
    with pytest.raises(ValueError):
        queue.create(source="test", action_type="not_a_type", summary="x", risk_level="low")


def test_create_redacts_payload_secrets(queue):
    approval = queue.create(
        source="test", action_type="email_send", summary="x", risk_level="low",
        payload={"to": "bob@example.com", "auth_token": "sekrit"},
    )
    assert approval.payload["auth_token"] == "[REDACTED]"
    assert approval.payload["to"] == "bob@example.com"


def test_approve_transitions_status(queue):
    approval = queue.create(source="test", action_type="other", summary="x", risk_level="low")
    approved = queue.approve(approval.approval_id)
    assert approved.status == "approved"


def test_deny_transitions_status(queue):
    approval = queue.create(source="test", action_type="other", summary="x", risk_level="low")
    denied = queue.deny(approval.approval_id)
    assert denied.status == "denied"


def test_approve_unknown_id_returns_none(queue):
    assert queue.approve("nope") is None


def test_expired_approval_detected(queue):
    approval = queue.create(source="test", action_type="other", summary="x", risk_level="low", expiry_hours=-1)
    fetched = queue.get(approval.approval_id)
    assert fetched.status == "expired"


def test_list_filters_by_status(queue):
    a1 = queue.create(source="t", action_type="other", summary="a", risk_level="low")
    a2 = queue.create(source="t", action_type="other", summary="b", risk_level="low")
    queue.approve(a1.approval_id)
    pending = queue.list(status="pending")
    approved = queue.list(status="approved")
    assert len(pending) == 1
    assert len(approved) == 1


def test_execute_without_executor_returns_dry_run(queue):
    approval = queue.create(source="t", action_type="agent_stop", summary="stop x", risk_level="high")
    queue.approve(approval.approval_id)
    result = queue.execute(approval.approval_id)
    assert result["ok"] is False
    assert "executor not implemented" in result["short_summary"]


def test_execute_with_registered_executor_runs(queue):
    approval = queue.create(source="t", action_type="file_change", summary="touch a file", risk_level="low")
    queue.approve(approval.approval_id)
    register_executor("file_change", lambda a: {"ok": True, "short_summary": "done"})
    try:
        result = queue.execute(approval.approval_id)
        assert result["ok"] is True
    finally:
        from src.warden.resident.approvals import _EXECUTORS
        _EXECUTORS.pop("file_change", None)


def test_execute_requires_approved_status(queue):
    approval = queue.create(source="t", action_type="other", summary="x", risk_level="low")
    result = queue.execute(approval.approval_id)
    assert result["ok"] is False
    assert "not approved" in result["short_summary"] or "pending" in result["short_summary"]
