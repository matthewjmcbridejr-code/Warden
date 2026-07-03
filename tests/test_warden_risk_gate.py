"""Tests for Warden Risk Gate."""
import pytest
from src.warden.risk_gate import (
    RiskGate,
    RiskGateViolation,
    RiskLevel,
    classify_action,
    is_safe,
    gate_or_raise,
)


def test_read_actions_are_safe():
    assert classify_action("read_file") == RiskLevel.read_only
    assert classify_action("search_memories") == RiskLevel.read_only
    assert classify_action("list_projects") == RiskLevel.read_only
    assert classify_action("get_health") == RiskLevel.read_only


def test_destructive_actions_classified():
    assert classify_action("delete_file") == RiskLevel.destructive
    assert classify_action("deploy_service") == RiskLevel.destructive
    assert classify_action("send_email") == RiskLevel.destructive
    assert classify_action("force_push") == RiskLevel.destructive


def test_financial_actions_classified():
    assert classify_action("purchase_credits") == RiskLevel.financial
    assert classify_action("charge_card") == RiskLevel.financial


def test_identity_security_classified():
    assert classify_action("rotate_secret") == RiskLevel.identity_security
    assert classify_action("read_env") == RiskLevel.identity_security


def test_gate_allows_read_only():
    gate = RiskGate(max_level=RiskLevel.safe_write)
    level = gate.check("read_file")
    assert level == RiskLevel.read_only


def test_gate_blocks_destructive():
    gate = RiskGate(max_level=RiskLevel.safe_write)
    with pytest.raises(RiskGateViolation):
        gate.check("delete_file")


def test_gate_blocks_financial_always():
    gate = RiskGate(max_level=RiskLevel.financial)
    with pytest.raises(RiskGateViolation):
        gate.check("purchase_credits")


def test_gate_blocks_identity_always():
    gate = RiskGate(max_level=RiskLevel.identity_security)
    with pytest.raises(RiskGateViolation):
        gate.check("read_env")


def test_approved_actions_bypass_safe_write_gate():
    gate = RiskGate(max_level=RiskLevel.safe_write, approved_actions=["git_commit"])
    level = gate.check("git_commit", approved=True)
    assert level == RiskLevel.repo_mutation


def test_approved_cannot_bypass_always_block():
    gate = RiskGate(max_level=RiskLevel.identity_security, approved_actions=["read_env"])
    # always-block actions still require `approved=True` at call site
    with pytest.raises(RiskGateViolation):
        gate.check("read_env")  # approved=False by default


def test_is_safe_helper():
    assert is_safe("search_memories")
    assert not is_safe("delete_file")


def test_gate_or_raise():
    level = gate_or_raise("write_file", max_level=RiskLevel.safe_write)
    assert level == RiskLevel.safe_write
    with pytest.raises(RiskGateViolation):
        gate_or_raise("deploy_service", max_level=RiskLevel.safe_write)


def test_repo_mutation_blocked_at_safe_write():
    gate = RiskGate(max_level=RiskLevel.safe_write)
    with pytest.raises(RiskGateViolation):
        gate.check("git_commit")


def test_repo_mutation_allowed_at_repo_mutation_level():
    gate = RiskGate(max_level=RiskLevel.repo_mutation, approved_actions=["git_commit"])
    level = gate.check("git_commit", approved=True)
    assert level == RiskLevel.repo_mutation
