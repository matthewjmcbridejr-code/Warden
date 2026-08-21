"""Tests for Execution Truth invariants across Agent Runtime and Computer Use."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from src.warden.agent_runtime import (
    WardenAgentRuntime,
    ResolvedProvider,
    ToolCallResult,
)


def test_auth_failure_before_click_never_claims_execution():
    """Verify that when Computer Use fails with an auth error, Warden prose states truth and never claims the button was clicked."""
    runtime = WardenAgentRuntime()

    # Mock tool registry execution to return an authentic auth failure
    failed_tool_res = ToolCallResult(
        tool_name="computer_use",
        arguments={"objective": "Click delete account button"},
        result={
            "ok": False,
            "session_id": "session-auth-fail-1",
            "status": "failed",
            "error": "Computer Use unavailable: Google Cloud Vertex AI not configured: No credentials found",
            "result": None,
            "evidence": [],
        },
    )

    with patch.object(runtime.registry, "execute", return_value=failed_tool_res):
        with patch.object(runtime, "_call_model_step") as mock_step:
            with patch("src.warden.agent_runtime.resolve_inference_provider", return_value=ResolvedProvider(provider_type="mock", model="mock-model", endpoint="http://mock")):
                # First turn: model decides to call computer_use
                # Second turn: model tries to falsely synthesize "I clicked the button"
                mock_step.side_effect = [
                    ("", [{"name": "computer_use", "arguments": {"objective": "Click delete account button"}}]),
                    ("You clicked the Delete account test button exactly once.", []),
                ]

                result = runtime.run("Warden", "conv_truth_1", "use the browser to click the Delete account button")

                # Invariant: Structured outcome overrides hallucination
                assert result.reply != "You clicked the Delete account test button exactly once."
                assert "Browser work stopped before the requested action executed" in result.reply
                assert "Google Cloud authentication is required" in result.reply


def test_denied_action_never_claims_execution():
    """Verify that when an action is denied by the operator, Warden prose truthfully states prevention."""
    runtime = WardenAgentRuntime()

    denied_tool_res = ToolCallResult(
        tool_name="computer_use",
        arguments={"objective": "Click confirm order"},
        result={
            "ok": True,
            "session_id": "session-denied-1",
            "status": "completed",
            "result": "Action prevented: Operator denied action",
            "error": None,
            "evidence": [],
        },
    )

    with patch.object(runtime.registry, "execute", return_value=denied_tool_res):
        with patch.object(runtime, "_call_model_step") as mock_step:
            with patch("src.warden.agent_runtime.resolve_inference_provider", return_value=ResolvedProvider(provider_type="mock", model="mock-model", endpoint="http://mock")):
                mock_step.side_effect = [
                    ("", [{"name": "computer_use", "arguments": {"objective": "Click confirm order"}}]),
                    ("Order was placed successfully.", []),
                ]

                result = runtime.run("Warden", "conv_truth_2", "use the browser to submit order")
                assert "Order was placed successfully" not in result.reply
                assert "prevented and was not executed" in result.reply
