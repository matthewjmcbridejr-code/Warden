"""Unit and integration tests for Warden Computer Use subsystem."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.warden.computer.models import (
    ActionType,
    ComputerAction,
    ComputerObservation,
    ComputerSession,
    ConfirmationRequest,
    SessionStatus,
)
from src.warden.computer.confirmations import check_confirmation_required
from src.warden.computer.screenshots import save_screenshot, encode_screenshot_base64
from src.warden.computer.executors.playwright_executor import PlaywrightBrowserExecutor
from src.warden.computer.executors.linux_desktop_executor import LinuxDesktopExecutor
from src.warden.computer.providers.mock_provider import MockComputerProvider
from src.warden.computer.providers.gemini_vertex import GeminiVertexComputerProvider
from src.warden.computer.service import ComputerUseService
from src.warden.agent_runtime import WardenToolRegistry, WardenAgentRuntime, handle_computer_use


def test_registry_contains_computer_use():
    registry = WardenToolRegistry()
    tool = registry.get("computer_use")
    assert tool is not None
    assert tool.name == "computer_use"
    assert "objective" in tool.parameters["required"]
    assert "environment" in tool.parameters["properties"]

    tool_list = registry.list_tools()
    names = [t["function"]["name"] for t in tool_list]
    assert "computer_use" in names


def test_computer_use_models():
    action = ComputerAction(
        action_type=ActionType.CLICK,
        x=150,
        y=320,
        summary="Click submit",
        requires_confirmation=False
    )
    d = action.to_dict()
    assert d["action_type"] == "click"
    assert d["x"] == 150
    assert d["y"] == 320

    session = ComputerSession(
        session_id="comp-test-123",
        objective="Test objective",
        environment="browser",
        status=SessionStatus.RUNNING,
    )
    summary = session.to_summary_dict()
    assert summary["session_id"] == "comp-test-123"
    assert summary["ok"] is False
    assert summary["steps"] == 0


def test_confirmation_policy():
    safe_action = ComputerAction(action_type=ActionType.CLICK, x=50, y=50, summary="Click navigation link")
    assert not check_confirmation_required(safe_action)

    delete_action = ComputerAction(action_type=ActionType.CLICK, x=100, y=100, summary="Click delete account button")
    assert check_confirmation_required(delete_action)

    buy_action = ComputerAction(action_type=ActionType.TYPE, text="buy now", summary="Typed purchase command")
    assert check_confirmation_required(buy_action)

    explicit_action = ComputerAction(action_type=ActionType.CLICK, requires_confirmation=True)
    assert check_confirmation_required(explicit_action)


def test_screenshot_saving_and_encoding(tmp_path):
    dummy_bytes = b"fake-jpeg-data"
    b64 = encode_screenshot_base64(dummy_bytes)
    assert len(b64) > 0

    with patch("src.warden.computer.screenshots.SCREENSHOT_DIR", tmp_path):
        saved_path = save_screenshot(dummy_bytes, session_id="comp_test", step_index=1)
        assert Path(saved_path).exists()
        assert Path(saved_path).read_bytes() == dummy_bytes


def test_mock_provider_execution():
    actions = [
        ComputerAction(action_type=ActionType.NAVIGATE, url="about:blank", summary="Navigated"),
        ComputerAction(action_type=ActionType.CLICK, x=10, y=10, summary="Clicked"),
        ComputerAction(action_type=ActionType.COMPLETE, text="Done testing", summary="Finished"),
    ]
    provider = MockComputerProvider(actions=actions)
    session = ComputerSession(session_id="test", objective="mock goal")
    obs = ComputerObservation()

    a1 = provider.plan_next_action(session, obs)
    assert a1.action_type == ActionType.NAVIGATE
    a2 = provider.plan_next_action(session, obs)
    assert a2.action_type == ActionType.CLICK
    a3 = provider.plan_next_action(session, obs)
    assert a3.action_type == ActionType.COMPLETE


def test_playwright_executor_lifecycle():
    executor = PlaywrightBrowserExecutor(headless=True)
    assert not executor.is_active()

    executor.start(initial_url="about:blank")
    assert executor.is_active()

    dims = executor.get_dimensions()
    assert dims == (1280, 800)

    obs = executor.capture_screenshot()
    assert obs.screenshot_bytes is not None
    assert len(obs.screenshot_bytes) > 0
    assert obs.url == "about:blank"

    # Execute action
    click_act = ComputerAction(action_type=ActionType.CLICK, x=50, y=50, summary="Clicked")
    obs_after = executor.execute_action(click_act)
    assert obs_after.screenshot_bytes is not None

    executor.stop()
    assert not executor.is_active()


def test_computer_use_service_full_mock_run():
    actions = [
        ComputerAction(action_type=ActionType.NAVIGATE, url="about:blank", summary="Navigated to blank"),
        ComputerAction(action_type=ActionType.CLICK, x=20, y=20, summary="Clicked top left"),
        ComputerAction(action_type=ActionType.COMPLETE, text="Mock execution succeeded!", summary="Completed"),
    ]
    events = []
    def on_event(name, data):
        events.append((name, data))

    service = ComputerUseService()
    result = service.run(
        objective="Validate mock service run",
        environment="browser",
        start_url="about:blank",
        max_steps=5,
        provider=MockComputerProvider(actions=actions),
        executor=PlaywrightBrowserExecutor(headless=True),
        event_callback=on_event,
    )

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["steps"] == 3
    assert result["result"] == "Mock execution succeeded!"
    assert len(result["evidence"]) == 3
    assert any(e[0] == "computer_session_started" for e in events)
    assert any(e[0] == "computer_action" for e in events)
    assert any(e[0] == "computer_session_completed" for e in events)


def test_computer_use_service_max_steps():
    # Provider never returns COMPLETE
    infinite_actions = [
        ComputerAction(action_type=ActionType.WAIT, seconds=0.1, summary="Waiting")
        for _ in range(10)
    ]
    service = ComputerUseService()
    result = service.run(
        objective="Test step overflow",
        environment="browser",
        start_url="about:blank",
        max_steps=3,
        provider=MockComputerProvider(actions=infinite_actions),
        executor=PlaywrightBrowserExecutor(headless=True),
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["steps"] == 3
    assert "maximum action count" in result["error"]


def test_handle_computer_use_dispatch():
    with patch.object(ComputerUseService, "run") as mock_run:
        mock_run.return_value = {"ok": True, "result": "Found docs", "steps": 2}
        res = handle_computer_use(objective="Find docs", environment="browser")
        assert res["ok"] is True
        assert res["result"] == "Found docs"
