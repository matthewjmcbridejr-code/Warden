"""Unit and integration tests for Warden Computer Use subsystem and Mission Control runtime contract."""

import json
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.warden.app import create_app
from src.warden.computer.models import (
    ActionType,
    ComputerAction,
    ComputerObservation,
    ComputerSession,
    ConfirmationRequest,
    SessionStatus,
)
from src.warden.computer.confirmations import (
    ConfirmationStore,
    check_confirmation_required,
    default_confirmation_store,
)
from src.warden.computer.screenshots import save_screenshot, encode_screenshot_base64
from src.warden.computer.executors.base import BaseComputerExecutor
from src.warden.computer.executors.playwright_executor import PlaywrightBrowserExecutor
from src.warden.computer.executors.linux_desktop_executor import LinuxDesktopExecutor
from src.warden.computer.providers.mock_provider import MockComputerProvider
from src.warden.computer.providers.gemini_vertex import GeminiVertexComputerProvider
from src.warden.computer.service import ComputerUseService, default_session_registry
from src.warden.agent_runtime import WardenToolRegistry, WardenAgentRuntime, handle_computer_use
from src.warden.group_chat import GroupChatStore


@pytest.fixture(autouse=True)
def clean_stores(tmp_path):
    """Ensure clean confirmation store and group chat db per test."""
    default_confirmation_store.clear()
    default_session_registry.clear()
    yield
    default_confirmation_store.clear()
    default_session_registry.clear()


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
        requires_confirmation=False,
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
    assert summary["is_waiting_for_confirmation"] is False


def test_confirmation_policy():
    safe_action = ComputerAction(action_type=ActionType.CLICK, x=50, y=50, summary="Click navigation link")
    assert not check_confirmation_required(safe_action)

    delete_action = ComputerAction(action_type=ActionType.CLICK, x=100, y=100, summary="Click delete account button")
    assert check_confirmation_required(delete_action)

    buy_action = ComputerAction(action_type=ActionType.TYPE, text="buy now", summary="Typed purchase command")
    assert check_confirmation_required(buy_action)

    explicit_action = ComputerAction(action_type=ActionType.CLICK, requires_confirmation=True)
    assert check_confirmation_required(explicit_action)

    completed_sensitive_action = ComputerAction(
        action_type=ActionType.COMPLETE,
        text="The delete account test action executed once.",
        summary="Finished after the approved delete account action.",
    )
    assert not check_confirmation_required(completed_sensitive_action)


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

    click_act = ComputerAction(action_type=ActionType.CLICK, x=50, y=50, summary="Clicked")
    obs_after = executor.execute_action(click_act)
    assert obs_after.screenshot_bytes is not None

    executor.stop()
    assert not executor.is_active()


def test_playwright_executor_does_not_swallow_action_failure():
    executor = PlaywrightBrowserExecutor(headless=True)
    page = MagicMock()
    page.is_closed.return_value = False
    page.mouse.click.side_effect = RuntimeError("target detached")
    executor._page = page

    with pytest.raises(RuntimeError, match="Browser action 'click' failed"):
        executor.execute_action(ComputerAction(action_type=ActionType.CLICK, x=20, y=30))


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


def test_confirmation_required_action_does_not_call_executor_before_approval():
    """Verify that a sensitive action halts and does NOT call executor.execute_action before approval."""
    store = ConfirmationStore()
    mock_executor = MagicMock(spec=BaseComputerExecutor)
    mock_executor.capture_screenshot.return_value = ComputerObservation(url="https://app.test", title="App")

    sensitive_action = ComputerAction(
        action_type=ActionType.CLICK,
        x=50,
        y=50,
        summary="Click delete database",
    )
    provider = MockComputerProvider(actions=[sensitive_action])

    service = ComputerUseService(confirmation_store=store, confirmation_timeout=0.2)

    # Run should time out / fail safe without calling execute_action
    result = service.run(
        objective="Test confirmation hold",
        environment="browser",
        max_steps=2,
        provider=provider,
        executor=mock_executor,
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert "prevented" in result["error"] or "expired" in result["error"]
    # CRITICAL: executor.execute_action MUST NEVER HAVE BEEN CALLED
    assert mock_executor.execute_action.call_count == 0


def test_approved_action_executes_exactly_once():
    """Verify that explicit approval resumes execution and calls executor exactly once."""
    store = ConfirmationStore()
    mock_executor = MagicMock(spec=BaseComputerExecutor)
    mock_executor.capture_screenshot.return_value = ComputerObservation(url="https://app.test", title="App")
    mock_executor.execute_action.return_value = ComputerObservation(url="https://app.test/deleted", title="Done")

    sensitive_action = ComputerAction(
        action_type=ActionType.CLICK,
        x=50,
        y=50,
        summary="Click delete database",
    )
    complete_action = ComputerAction(action_type=ActionType.COMPLETE, text="Database deleted successfully")
    provider = MockComputerProvider(actions=[sensitive_action, complete_action])

    service = ComputerUseService(confirmation_store=store, confirmation_timeout=2.0)

    def _auto_approver():
        # Poll store for pending confirmation and approve
        for _ in range(20):
            pending = store.list_pending()
            if pending:
                request = pending[0]
                ok, msg, conf = store.resolve_confirmation(
                    request.confirmation_id,
                    decision="approve",
                    operator_id="matt",
                    expected_session_id=request.session_id,
                    expected_action_id=request.action_id,
                )
                assert ok is True
                break
            time.sleep(0.05)

    thread = threading.Thread(target=_auto_approver)
    thread.start()

    result = service.run(
        objective="Test approval path",
        environment="browser",
        max_steps=5,
        provider=provider,
        executor=mock_executor,
    )
    thread.join()

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["result"] == "Database deleted successfully"
    # Action executed exactly once
    assert mock_executor.execute_action.call_count == 1


def test_denied_action_never_executes():
    """Verify that operator denial prevents executor execution completely."""
    store = ConfirmationStore()
    mock_executor = MagicMock(spec=BaseComputerExecutor)
    mock_executor.capture_screenshot.return_value = ComputerObservation(url="https://app.test", title="App")

    sensitive_action = ComputerAction(
        action_type=ActionType.CLICK,
        x=50,
        y=50,
        summary="Click delete database",
    )
    provider = MockComputerProvider(actions=[sensitive_action])

    service = ComputerUseService(confirmation_store=store, confirmation_timeout=2.0)

    def _auto_denier():
        for _ in range(20):
            pending = store.list_pending()
            if pending:
                request = pending[0]
                ok, msg, conf = store.resolve_confirmation(
                    request.confirmation_id,
                    decision="deny",
                    operator_id="matt",
                    expected_session_id=request.session_id,
                    expected_action_id=request.action_id,
                )
                assert ok is True
                break
            time.sleep(0.05)

    thread = threading.Thread(target=_auto_denier)
    thread.start()

    result = service.run(
        objective="Test deny path",
        environment="browser",
        max_steps=5,
        provider=provider,
        executor=mock_executor,
    )
    thread.join()

    assert result["ok"] is True
    assert "prevented" in result["result"]
    # Action was NEVER executed
    assert mock_executor.execute_action.call_count == 0


def test_stale_mismatched_approval_cannot_authorize_action():
    """Verify that mismatched session_id, action_id, or replayed resolution is rejected."""
    store = ConfirmationStore()
    act = ComputerAction(action_type=ActionType.CLICK, summary="Click remove user")
    conf = store.create_confirmation(session_id="session_A", action=act, step_idx=1)

    # 1. Mismatched session ID
    ok1, msg1, _ = store.resolve_confirmation(conf.confirmation_id, decision="approve", expected_session_id="session_B", expected_action_id="session_A_step_1")
    assert ok1 is False
    assert "Mismatched session ID" in msg1

    # 2. Mismatched action ID
    ok2, msg2, _ = store.resolve_confirmation(conf.confirmation_id, decision="approve", expected_session_id="session_A", expected_action_id="session_A_step_99")
    assert ok2 is False
    assert "Mismatched action ID" in msg2

    # 3. Successful resolution
    ok3, msg3, resolved = store.resolve_confirmation(conf.confirmation_id, decision="approve", expected_session_id="session_A", expected_action_id="session_A_step_1")
    assert ok3 is True
    assert resolved.status == "approved"

    # 4. Replay attempt on already resolved confirmation
    ok4, msg4, _ = store.resolve_confirmation(
        conf.confirmation_id,
        decision="approve",
        expected_session_id="session_A",
        expected_action_id="session_A_step_1",
    )
    assert ok4 is False
    assert "already resolved" in msg4


def test_live_start_action_observation_events_emitted_before_completion():
    """Verify that live lifecycle events are emitted chronologically before session completion."""
    actions = [
        ComputerAction(action_type=ActionType.NAVIGATE, url="https://example.com", summary="Navigating"),
        ComputerAction(action_type=ActionType.CLICK, x=100, y=100, summary="Clicking button"),
        ComputerAction(action_type=ActionType.COMPLETE, text="Finished!"),
    ]
    mock_executor = MagicMock(spec=BaseComputerExecutor)
    mock_executor.capture_screenshot.return_value = ComputerObservation(url="https://example.com", title="Example")
    mock_executor.execute_action.return_value = ComputerObservation(url="https://example.com/clicked", title="Clicked")

    emitted_events = []

    def _event_cb(event_type, payload):
        emitted_events.append((event_type, payload))

    service = ComputerUseService()
    result = service.run(
        objective="Validate live event order",
        environment="browser",
        max_steps=5,
        provider=MockComputerProvider(actions=actions),
        executor=mock_executor,
        event_callback=_event_cb,
    )

    assert result["ok"] is True
    event_names = [e[0] for e in emitted_events]

    # Session started must be first
    assert event_names[0] == "computer_session_started"
    # Session completed must be last
    assert event_names[-1] == "computer_session_completed"

    # Live actions and observations must be present in the middle
    assert "computer_action" in event_names
    assert "computer_observation" in event_names
    assert event_names.index("computer_action") < event_names.index("computer_session_completed")


def test_pending_confirmation_produces_authoritative_needs_user_state():
    """Verify that when confirmation is requested, session reflects WAITING_FOR_CONFIRMATION and store shows pending."""
    store = ConfirmationStore()
    mock_executor = MagicMock(spec=BaseComputerExecutor)
    mock_executor.capture_screenshot.return_value = ComputerObservation(url="https://app.test", title="App")

    sensitive_action = ComputerAction(action_type=ActionType.CLICK, summary="Click wipe all records")
    provider = MockComputerProvider(actions=[sensitive_action])
    service = ComputerUseService(confirmation_store=store, confirmation_timeout=1.0)

    observed_session_state = []

    def _checker():
        for _ in range(20):
            pending = store.list_pending()
            if pending:
                conf = pending[0]
                session = service.get_session(conf.session_id)
                if session:
                    observed_session_state.append((session.status, session.is_waiting_for_confirmation, conf.status))
                    store.resolve_confirmation(
                        conf.confirmation_id,
                        decision="deny",
                        expected_session_id=conf.session_id,
                        expected_action_id=conf.action_id,
                    )
                    break
            time.sleep(0.05)

    thread = threading.Thread(target=_checker)
    thread.start()

    service.run(
        objective="Needs user test",
        environment="browser",
        provider=provider,
        executor=mock_executor,
    )
    thread.join()

    assert len(observed_session_state) == 1
    status, is_waiting, conf_status = observed_session_state[0]
    assert status == SessionStatus.WAITING_FOR_CONFIRMATION
    assert is_waiting is True
    assert conf_status == "pending"


def test_completed_failed_session_clears_live_state_truthfully():
    """Verify that completed or failed sessions clear active confirmations and report final state truthfully."""
    store = ConfirmationStore()
    mock_executor = MagicMock(spec=BaseComputerExecutor)
    mock_executor.capture_screenshot.return_value = ComputerObservation(url="https://app.test", title="App")

    complete_action = ComputerAction(action_type=ActionType.COMPLETE, text="Task complete")
    provider = MockComputerProvider(actions=[complete_action])
    service = ComputerUseService(confirmation_store=store)

    result = service.run(
        objective="Clean exit",
        environment="browser",
        provider=provider,
        executor=mock_executor,
    )

    assert result["ok"] is True
    assert len(store.list_pending()) == 0

    session = service.get_session(result["session_id"])
    assert session is not None
    assert session.status == SessionStatus.COMPLETED
    assert session.active_confirmation_id is None


def test_computer_api_rest_endpoints(tmp_path):
    """Test REST endpoints for confirmations, session inventory, and safe screenshots."""
    app = create_app()
    client = TestClient(app)

    # 1. Create a pending confirmation in default store
    act = ComputerAction(action_type=ActionType.CLICK, summary="Click delete workspace")
    conf = default_confirmation_store.create_confirmation(session_id="comp_test_session", action=act, step_idx=1)

    # 2. GET /api/mcharness/computer/confirmations/pending
    res_pending = client.get("/api/mcharness/computer/confirmations/pending")
    assert res_pending.status_code == 200
    data_p = res_pending.json()
    assert data_p["ok"] is True
    assert data_p["count"] >= 1
    assert any(c["confirmation_id"] == conf.confirmation_id for c in data_p["confirmations"])

    # 3. GET /api/mcharness/computer/confirmations/{id}
    res_conf = client.get(f"/api/mcharness/computer/confirmations/{conf.confirmation_id}")
    assert res_conf.status_code == 200
    assert res_conf.json()["confirmation"]["status"] == "pending"

    # 4. POST /api/mcharness/computer/confirmations/{id}/resolve (mismatched session fails)
    res_bad = client.post(
        f"/api/mcharness/computer/confirmations/{conf.confirmation_id}/resolve",
        json={
            "decision": "approve",
            "expected_session_id": "wrong_session",
            "expected_action_id": conf.action_id,
        },
    )
    assert res_bad.status_code == 400

    # 5. POST /api/mcharness/computer/confirmations/{id}/resolve (success)
    res_ok = client.post(
        f"/api/mcharness/computer/confirmations/{conf.confirmation_id}/resolve",
        json={
            "decision": "approve",
            "expected_session_id": "comp_test_session",
            "expected_action_id": conf.action_id,
            "operator_id": "matt",
        },
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["ok"] is True
    assert res_ok.json()["confirmation"]["status"] == "approved"

    # 6. GET /api/mcharness/computer/screenshots/{filename}
    with patch("src.warden.computer.api.SCREENSHOT_DIR", tmp_path):
        dummy_file = tmp_path / "test_screen.jpg"
        dummy_file.write_bytes(b"jpeg-image-bytes")

        res_img = client.get("/api/mcharness/computer/screenshots/test_screen.jpg")
        assert res_img.status_code == 200
        assert res_img.content == b"jpeg-image-bytes"
        assert "no-store" in res_img.headers["cache-control"]
        assert "public" not in res_img.headers["cache-control"]

        # Traversal attempt returns 404 or sanitized
        res_trav = client.get("/api/mcharness/computer/screenshots/../../etc/passwd")
        assert res_trav.status_code in (400, 404)


def test_live_service_session_is_returned_by_authoritative_session_api():
    service = ComputerUseService()
    executor = MagicMock(spec=BaseComputerExecutor)
    executor.capture_screenshot.return_value = ComputerObservation(url="https://example.com", title="Example")
    result = service.run(
        objective="Inspect the real session registry",
        provider=MockComputerProvider(actions=[ComputerAction(action_type=ActionType.COMPLETE, text="Done")]),
        executor=executor,
    )

    client = TestClient(create_app())
    listed = client.get("/api/mcharness/computer/sessions")
    looked_up = client.get(f"/api/mcharness/computer/sessions/{result['session_id']}")

    assert listed.status_code == 200
    assert any(item["session_id"] == result["session_id"] for item in listed.json()["sessions"])
    assert looked_up.status_code == 200
    assert looked_up.json()["session"]["objective"] == "Inspect the real session registry"


def test_confirmation_api_requires_complete_action_binding():
    action = ComputerAction(action_type=ActionType.CLICK, summary="Click delete workspace")
    conf = default_confirmation_store.create_confirmation("bound_session", action, step_idx=4)
    client = TestClient(create_app())

    missing = client.post(
        f"/api/mcharness/computer/confirmations/{conf.confirmation_id}/resolve",
        json={"decision": "approve"},
    )
    wrong_action = client.post(
        f"/api/mcharness/computer/confirmations/{conf.confirmation_id}/resolve",
        json={
            "decision": "approve",
            "expected_session_id": conf.session_id,
            "expected_action_id": "another-action",
        },
    )

    assert missing.status_code == 422
    assert wrong_action.status_code == 400
    assert default_confirmation_store.get_confirmation(conf.confirmation_id).status == "pending"


def test_denial_cannot_be_replayed_as_approval_and_expired_confirmation_cannot_execute():
    store = ConfirmationStore()
    action = ComputerAction(action_type=ActionType.CLICK, summary="Click delete workspace")
    denied = store.create_confirmation("session-denied", action, step_idx=1)
    ok, _, _ = store.resolve_confirmation(
        denied.confirmation_id,
        decision="deny",
        expected_session_id=denied.session_id,
        expected_action_id=denied.action_id,
    )
    replay_ok, replay_message, _ = store.resolve_confirmation(
        denied.confirmation_id,
        decision="approve",
        expected_session_id=denied.session_id,
        expected_action_id=denied.action_id,
    )

    expired = store.create_confirmation("session-expired", action, step_idx=2)
    status, _ = store.wait_for_decision(expired.confirmation_id, timeout_seconds=0.001)
    expired_ok, expired_message, _ = store.resolve_confirmation(
        expired.confirmation_id,
        decision="approve",
        expected_session_id=expired.session_id,
        expected_action_id=expired.action_id,
    )

    assert ok is True
    assert replay_ok is False
    assert "already resolved" in replay_message
    assert status == "expired"
    assert expired_ok is False
    assert "expired" in expired_message


def test_approval_for_confirmation_a_cannot_unblock_action_b():
    store = ConfirmationStore()
    action = ComputerAction(action_type=ActionType.CLICK, summary="Click delete workspace")
    conf_a = store.create_confirmation("session-A", action, step_idx=1)
    conf_b = store.create_confirmation("session-B", action, step_idx=2)

    wrong_ok, _, _ = store.resolve_confirmation(
        conf_a.confirmation_id,
        decision="approve",
        expected_session_id=conf_b.session_id,
        expected_action_id=conf_b.action_id,
    )
    right_ok, _, _ = store.resolve_confirmation(
        conf_a.confirmation_id,
        decision="approve",
        expected_session_id=conf_a.session_id,
        expected_action_id=conf_a.action_id,
    )

    assert wrong_ok is False
    assert right_ok is True
    assert store.get_confirmation(conf_b.confirmation_id).status == "pending"


def test_executor_exception_after_approval_is_never_reported_as_executed():
    store = ConfirmationStore()
    executor = MagicMock(spec=BaseComputerExecutor)
    executor.capture_screenshot.return_value = ComputerObservation(url="https://app.test", title="App")
    executor.execute_action.side_effect = RuntimeError("browser rejected click")
    action = ComputerAction(action_type=ActionType.CLICK, summary="Click delete workspace")
    service = ComputerUseService(confirmation_store=store, confirmation_timeout=2.0)
    emitted = []

    def approve_exact_action():
        for _ in range(40):
            pending = store.list_pending()
            if pending:
                request = pending[0]
                store.resolve_confirmation(
                    request.confirmation_id,
                    decision="approve",
                    expected_session_id=request.session_id,
                    expected_action_id=request.action_id,
                )
                return
            time.sleep(0.025)

    thread = threading.Thread(target=approve_exact_action)
    thread.start()
    result = service.run(
        objective="Prove execution failure truth",
        provider=MockComputerProvider(actions=[action]),
        executor=executor,
        event_callback=lambda name, payload: emitted.append((name, payload)),
    )
    thread.join()

    assert result["status"] == "failed"
    assert "browser rejected click" in result["error"]
    assert not any(name == "computer_action_executed" for name, _ in emitted)
    resolved = [payload for name, payload in emitted if name == "computer_confirmation_resolved"]
    assert resolved and resolved[-1]["executed"] is False


def test_agent_runtime_live_group_chat_bridge(tmp_path):
    """Verify that handle_computer_use bridges live events into GroupChatStore in real-time."""
    db_file = tmp_path / "group_chat.sqlite"
    store = GroupChatStore(db_path=db_file)

    actions = [
        ComputerAction(action_type=ActionType.NAVIGATE, url="https://example.com", summary="Navigated to test site"),
        ComputerAction(action_type=ActionType.COMPLETE, text="Information retrieved successfully"),
    ]
    mock_executor = MagicMock(spec=BaseComputerExecutor)
    mock_executor.capture_screenshot.return_value = ComputerObservation(url="https://example.com", title="Example")
    mock_executor.execute_action.return_value = ComputerObservation(url="https://example.com", title="Example")

    with patch("src.warden.agent_runtime.GroupChatStore", return_value=store):
        with patch.object(GeminiVertexComputerProvider, "is_available", return_value=(True, "Available")):
            with patch("src.warden.computer.service.PlaywrightBrowserExecutor", return_value=mock_executor):
                with patch("src.warden.computer.service.GeminiVertexComputerProvider", return_value=MockComputerProvider(actions=actions)):
                    result = handle_computer_use(
                        objective="Retrieve test site info",
                        environment="browser",
                        max_steps=5,
                    )

    assert result["ok"] is True
    events = store.list_events()
    assert len(events) >= 3
    event_types = [e.event_type for e in events]
    assert "agent_working" in event_types
    assert "task_progress" in event_types
    assert "task_completed" in event_types
