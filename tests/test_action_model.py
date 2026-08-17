"""Unit tests for WardenActionV1 and secret redaction."""
from __future__ import annotations

from src.warden.action_model import WardenActionV1, redact_sensitive_arguments, compute_argument_fingerprint


def test_redact_sensitive_arguments():
    raw_args = {
        "command": "git push",
        "api_key": "dummy_val_123",
        "nested": {
            "password": "dummy_pass_123",
            "safe_field": "hello",
        },
    }
    redacted = redact_sensitive_arguments(raw_args)
    assert redacted["command"] == "git push"
    assert redacted["api_key"] == "[REDACTED_SECRET]"
    assert redacted["nested"]["password"] == "[REDACTED_SECRET]"
    assert redacted["nested"]["safe_field"] == "hello"


test_redact_sensitive_arguments()


def test_action_fingerprint_stability():
    args1 = {"path": "src/app.py", "line": 42}
    fp1 = compute_argument_fingerprint(args1)
    fp2 = compute_argument_fingerprint(args1)
    assert fp1 == fp2
    assert fp1.startswith("fp_")

    args_diff = {"path": "src/app.py", "line": 43}
    fp3 = compute_argument_fingerprint(args_diff)
    assert fp1 != fp3


def test_warden_action_factory():
    action = WardenActionV1.create(
        tool_name="warden_remember",
        arguments={"kind": "decision", "text": "Architecture change", "token": "abc_secret"},
        project="warden",
        risk_class="LOW_WRITE",
    )
    assert action.action.tool_name == "warden_remember"
    assert action.safe_argument_summary["token"] == "[REDACTED_SECRET]"
    assert action.safe_argument_summary["text"] == "Architecture change"
    assert action.argument_fingerprint.startswith("fp_")
