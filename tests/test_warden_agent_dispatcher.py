"""Tests for Warden Agent Dispatcher."""
import json
import tempfile
from pathlib import Path

import pytest

from src.warden.agent_dispatcher import (
    AgentDispatcher,
    build_prompt_file,
    _iter_tasks_by_status,
    LOG_DIR,
)
from src.warden.risk_gate import RiskGateViolation


@pytest.fixture
def tmp_board(tmp_path, monkeypatch):
    """Create a fake board root and monkeypatch BOARD_ROOT."""
    board = tmp_path / "_mctable"
    (board / "tasks" / "queued").mkdir(parents=True)
    (board / "tasks" / "claimed").mkdir(parents=True)
    (board / "tasks" / "completed").mkdir(parents=True)
    (board / "tasks" / "failed").mkdir(parents=True)
    (board / "activity").mkdir(parents=True)
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "BOARD_ROOT", board)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_path / "runs")
    return board


@pytest.fixture
def sample_task():
    return {
        "task_id": "test-task-001",
        "title": "Test Task",
        "description": "Do something safe.",
        "agent": "cl",
        "priority": "medium",
        "status": "queued",
    }


def _write_task(board: Path, status: str, task: dict):
    path = board / "tasks" / status / f"{task['task_id']}.json"
    path.write_text(json.dumps(task))
    return path


def test_build_prompt_file(tmp_path, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "LOG_DIR", tmp_path)
    task = {"task_id": "t1", "title": "T1", "description": "desc", "agent": "cl"}
    path = build_prompt_file(task)
    assert path.exists()
    content = path.read_text()
    assert "Warden Dispatched Task" in content
    assert "T1" in content
    assert "Required Closeout" in content
    assert "proof" in content


def test_dry_run_dispatches_without_launching(tmp_board, sample_task, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    path = _write_task(tmp_board, "queued", sample_task)
    dispatcher = AgentDispatcher(
        config={
            "enabled": True,
            "poll_interval_seconds": 1,
            "default_timeout_seconds": 30,
            "log_dir": str(tmp_board.parent / "runs"),
            "allowed_repo_roots": [],
            "agents": {"cl": {"enabled": True, "command_template": ["cl", "--prompt-file", "{prompt_file}"]}},
        },
        dry_run=True,
    )
    result = dispatcher.dispatch_task(sample_task, path)
    assert result.success
    assert "dry-run" in result.summary
    # Task should NOT be claimed (dry-run skips claim)
    assert not (tmp_board / "tasks" / "claimed" / "test-task-001.json").exists()


def test_ignores_disabled_agent(tmp_board, sample_task, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    path = _write_task(tmp_board, "queued", sample_task)
    dispatcher = AgentDispatcher(
        config={
            "enabled": True,
            "poll_interval_seconds": 1,
            "default_timeout_seconds": 30,
            "log_dir": str(tmp_board.parent / "runs"),
            "allowed_repo_roots": [],
            "agents": {"cl": {"enabled": False, "command_template": ["cl", "--prompt-file", "{prompt_file}"]}},
        },
        dry_run=True,
    )
    result = dispatcher.dispatch_task(sample_task, path)
    assert not result.success
    assert "No enabled agent" in result.summary


def test_skips_task_outside_allowed_paths(tmp_board, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    task = {
        "task_id": "bad-path-task",
        "title": "Bad",
        "description": "desc",
        "agent": "cl",
        "repo": "/etc/forbidden",
        "status": "queued",
    }
    path = _write_task(tmp_board, "queued", task)
    dispatcher = AgentDispatcher(
        config={
            "enabled": True,
            "poll_interval_seconds": 1,
            "default_timeout_seconds": 30,
            "log_dir": str(tmp_board.parent / "runs"),
            "allowed_repo_roots": ["/home/matt/workspaces"],
            "agents": {"cl": {"enabled": True, "command_template": ["cl", "--prompt-file", "{prompt_file}"]}},
        },
        dry_run=True,
    )
    result = dispatcher.dispatch_task(task, path)
    assert not result.success
    assert "allowed" in result.summary.lower()


def test_poll_once_returns_results(tmp_board, sample_task, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "BOARD_ROOT", tmp_board)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    _write_task(tmp_board, "queued", sample_task)
    dispatcher = AgentDispatcher(
        config={
            "enabled": True,
            "poll_interval_seconds": 1,
            "default_timeout_seconds": 30,
            "log_dir": str(tmp_board.parent / "runs"),
            "allowed_repo_roots": [],
            "agents": {"cl": {"enabled": True, "command_template": ["cl", "--prompt-file", "{prompt_file}"]}},
        },
        dry_run=True,
    )
    results = dispatcher.poll_once()
    assert len(results) == 1
    assert results[0].task_id == "test-task-001"


def test_command_not_found_returns_failure(tmp_board, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "BOARD_ROOT", tmp_board)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    task = {
        "task_id": "missing-cmd",
        "title": "Missing Cmd",
        "description": "desc",
        "agent": "cl",
        "status": "queued",
    }
    path = _write_task(tmp_board, "queued", task)
    dispatcher = AgentDispatcher(
        config={
            "enabled": True,
            "poll_interval_seconds": 1,
            "default_timeout_seconds": 5,
            "log_dir": str(tmp_board.parent / "runs"),
            "allowed_repo_roots": [],
            "agents": {"cl": {"enabled": True, "command_template": ["__no_such_cmd__", "--prompt-file", "{prompt_file}"]}},
        },
        dry_run=False,
    )
    result = dispatcher.dispatch_task(task, path)
    assert not result.success
    assert "not found" in result.summary or "exit" in result.summary


# ---------------------------------------------------------------------------
# Workspace Authority enforcement tests
# ---------------------------------------------------------------------------

# Matches the dynamic default in workspace_authority._CURRENT_CHECKOUT —
# the actual checkout, wherever it lives on this machine.
CANONICAL = str(Path(__file__).resolve().parents[1])
SCRATCH = "/home/matt/Documents/Warden"

_WA_CFG = {
    "enabled": True,
    "poll_interval_seconds": 1,
    "default_timeout_seconds": 30,
    "log_dir": "/tmp/warden-test-runs",
    "allowed_repo_roots": [CANONICAL],
    "agents": {"cl": {"enabled": True, "command_template": ["cl", "--prompt-file", "{prompt_file}"]}},
}


def test_canonical_cwd_passes_preflight(tmp_board, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "BOARD_ROOT", tmp_board)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    task = {
        "task_id": "can-1",
        "title": "Canonical Task",
        "description": "desc",
        "agent": "cl",
        "project_id": "warden",
        "repo_path": CANONICAL,
        "status": "queued",
    }
    path = _write_task(tmp_board, "queued", task)
    dispatcher = AgentDispatcher(config=_WA_CFG, dry_run=True)
    result = dispatcher.dispatch_task(task, path)
    # Should NOT be blocked by workspace preflight
    assert not result.workspace_drift


def test_scratch_cwd_blocks_dispatch(tmp_board, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "BOARD_ROOT", tmp_board)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    task = {
        "task_id": "scratch-1",
        "title": "Scratch Task",
        "description": "desc",
        "agent": "cl",
        "project_id": "warden",
        "repo_path": SCRATCH,
        "status": "queued",
    }
    path = _write_task(tmp_board, "queued", task)
    dispatcher = AgentDispatcher(config=_WA_CFG, dry_run=True)
    result = dispatcher.dispatch_task(task, path)
    assert not result.success
    assert result.workspace_drift


def test_blocked_result_includes_canonical_repo(tmp_board, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "BOARD_ROOT", tmp_board)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    task = {
        "task_id": "scratch-2",
        "title": "Bad Path",
        "description": "desc",
        "agent": "cl",
        "project_id": "warden",
        "repo_path": SCRATCH,
        "status": "queued",
    }
    path = _write_task(tmp_board, "queued", task)
    dispatcher = AgentDispatcher(config=_WA_CFG, dry_run=True)
    result = dispatcher.dispatch_task(task, path)
    assert result.workspace_drift
    assert result.canonical_repo == CANONICAL
    assert CANONICAL in (result.next_action or "")


def test_no_command_launches_from_scratch_cwd(tmp_board, monkeypatch):
    """Confirm the blocked result prevents any subprocess from launching."""
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "BOARD_ROOT", tmp_board)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    launched = []

    import subprocess as _sp
    original_run = _sp.run

    def mock_run(*args, **kwargs):
        launched.append(args)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(_sp, "run", mock_run)

    task = {
        "task_id": "scratch-3",
        "title": "No Launch",
        "description": "desc",
        "agent": "cl",
        "project_id": "warden",
        "repo_path": SCRATCH,
        "status": "queued",
    }
    path = _write_task(tmp_board, "queued", task)
    dispatcher = AgentDispatcher(config=_WA_CFG, dry_run=False)
    result = dispatcher.dispatch_task(task, path)
    assert not result.success
    assert result.workspace_drift
    # subprocess.run should not have been called for agent command
    assert not any("cl" in str(a) for a in launched)


def test_workspace_drift_writes_activity_event(tmp_board, monkeypatch):
    import src.warden.agent_dispatcher as mod
    monkeypatch.setattr(mod, "BOARD_ROOT", tmp_board)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_board.parent / "runs")
    task = {
        "task_id": "scratch-activity",
        "title": "Activity Event",
        "description": "desc",
        "agent": "cl",
        "project_id": "warden",
        "repo_path": SCRATCH,
        "status": "queued",
    }
    path = _write_task(tmp_board, "queued", task)
    dispatcher = AgentDispatcher(config=_WA_CFG, dry_run=True)
    dispatcher.dispatch_task(task, path)
    # Activity JSONL should have a workspace_drift_blocked event
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    activity_file = tmp_board / "activity" / date_str / "dispatcher.jsonl"
    assert activity_file.exists()
    events = [json.loads(l) for l in activity_file.read_text().splitlines() if l.strip()]
    drift_events = [e for e in events if e.get("event") == "workspace_drift_blocked"]
    assert len(drift_events) == 1
    assert drift_events[0]["task_id"] == "scratch-activity"
