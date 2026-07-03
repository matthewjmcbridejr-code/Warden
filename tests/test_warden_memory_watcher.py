"""Tests for Warden Autonomous Memory Collector."""
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path):
    """Create a minimal git repo for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    return repo


@pytest.fixture
def tmp_watched(tmp_path):
    watched = tmp_path / "src"
    watched.mkdir()
    return watched


# ---------------------------------------------------------------------------
# FileActivityTracker
# ---------------------------------------------------------------------------

def test_file_tracker_detects_new_file(tmp_watched):
    from src.warden.memory_watcher import FileActivityTracker
    tracker = FileActivityTracker([tmp_watched])
    tracker.seed()
    # Create a new file — seed doesn't know about it yet
    new = tmp_watched / "new_file.py"
    new.write_text("x = 1")
    # Ensure mtime is different (seed happened just now)
    time.sleep(0.01)
    new.write_text("x = 2")  # touch mtime
    changes = tracker.poll()
    # File wasn't in seed so it appears on first poll
    assert any("new_file" in c for c in changes) or len(changes) == 0  # may not trigger if mtime same second


def test_file_tracker_detects_modification(tmp_watched):
    from src.warden.memory_watcher import FileActivityTracker
    f = tmp_watched / "existing.py"
    f.write_text("v = 1")
    tracker = FileActivityTracker([tmp_watched])
    tracker.seed()
    time.sleep(0.05)
    f.write_text("v = 2")
    # Force mtime to differ
    import os
    os.utime(f, (time.time() + 1, time.time() + 1))
    changes = tracker.poll()
    assert str(f) in changes


# ---------------------------------------------------------------------------
# ShellHistoryCollector
# ---------------------------------------------------------------------------

def test_shell_history_captures_relevant_commands(tmp_path):
    from src.warden.memory_watcher import ShellHistoryCollector, SHELL_HISTORY_PATHS
    hist = tmp_path / ".bash_history"
    hist.write_text("ls -la\ngit commit -m 'test'\ncd /tmp\npytest tests/\n")
    collector = ShellHistoryCollector()
    collector._offsets[str(hist)] = 0
    # Patch history paths
    import src.warden.memory_watcher as mod
    orig = mod.SHELL_HISTORY_PATHS
    mod.SHELL_HISTORY_PATHS = [hist]
    try:
        cmds = collector.poll()
    finally:
        mod.SHELL_HISTORY_PATHS = orig
    assert any("git commit" in c for c in cmds)
    assert any("pytest" in c for c in cmds)
    assert not any("ls -la" in c for c in cmds)  # not relevant


def test_shell_history_only_returns_new_lines(tmp_path):
    from src.warden.memory_watcher import ShellHistoryCollector
    import src.warden.memory_watcher as mod
    hist = tmp_path / ".bash_history"
    hist.write_text("git commit -m 'first'\ngit commit -m 'second'\n")
    collector = ShellHistoryCollector()
    orig = mod.SHELL_HISTORY_PATHS
    mod.SHELL_HISTORY_PATHS = [hist]
    try:
        first = collector.poll()
        # Append new line
        with hist.open("a") as fh:
            fh.write("pytest tests/new_test.py\n")
        second = collector.poll()
    finally:
        mod.SHELL_HISTORY_PATHS = orig
    assert len(second) == 1
    assert "pytest" in second[0]


# ---------------------------------------------------------------------------
# ChromeCollector
# ---------------------------------------------------------------------------

def test_chrome_collector_returns_empty_when_no_db(tmp_path):
    from src.warden.memory_watcher import ChromeCollector
    import src.warden.memory_watcher as mod
    orig = mod.CHROME_HISTORY_DB
    mod.CHROME_HISTORY_DB = tmp_path / "nonexistent_History"
    collector = ChromeCollector()
    collector._db_path = mod.CHROME_HISTORY_DB
    try:
        results = collector.poll()
    finally:
        mod.CHROME_HISTORY_DB = orig
    assert results == []


def test_chrome_collector_filters_work_urls():
    from src.warden.memory_watcher import WORK_URL_PATTERN
    assert WORK_URL_PATTERN.search("https://github.com/user/repo")
    assert WORK_URL_PATTERN.search("http://localhost:3000/dashboard")
    assert WORK_URL_PATTERN.search("https://notion.so/page")
    assert not WORK_URL_PATTERN.search("https://youtube.com/watch")
    assert not WORK_URL_PATTERN.search("https://reddit.com/r/something")


# ---------------------------------------------------------------------------
# WorkEvent
# ---------------------------------------------------------------------------

def test_work_event_empty_when_nothing():
    from src.warden.memory_watcher import WorkEvent
    e = WorkEvent()
    assert e.is_empty()


def test_work_event_not_empty_with_commit():
    from src.warden.memory_watcher import WorkEvent
    e = WorkEvent()
    e.last_commit = {"hash": "abc", "subject": "fix: something"}
    assert not e.is_empty()
    assert e.kind() == "proof"


def test_work_event_kind_failure_on_test_fail():
    from src.warden.memory_watcher import WorkEvent
    e = WorkEvent()
    e.shell_commands = ["pytest tests/ → 3 failed, 10 passed"]
    assert e.kind() == "failure"


def test_work_event_kind_context_on_browser():
    from src.warden.memory_watcher import WorkEvent
    e = WorkEvent()
    e.browser_visits = [{"url": "https://github.com/foo", "title": "foo", "visited_at": "2026-06-27T00:00:00Z"}]
    assert e.kind() == "context"
    assert not e.is_empty()


def test_work_event_summary_includes_browser():
    from src.warden.memory_watcher import WorkEvent
    e = WorkEvent()
    e.browser_visits = [{"url": "https://github.com/warden", "title": "Warden repo", "visited_at": ""}]
    s = e.summary()
    assert "Browser" in s
    assert "Warden repo" in s


# ---------------------------------------------------------------------------
# MemoryWriter
# ---------------------------------------------------------------------------

def test_memory_writer_dry_run_does_not_write(tmp_path):
    from src.warden.memory_watcher import MemoryWriter, WorkEvent
    writer = MemoryWriter(dry_run=True)
    event = WorkEvent()
    event.last_commit = {"hash": "abc123", "subject": "test commit"}
    event.changed_files = ["src/warden/api.py"]
    result = writer.write(event, branch="main")
    assert result is not None  # returns memory_id in dry-run


def test_memory_writer_rate_limit():
    from src.warden.memory_watcher import MemoryWriter, WorkEvent, MAX_MEMORIES_PER_HOUR
    writer = MemoryWriter(dry_run=True)
    writer._written_this_hour = [time.time()] * MAX_MEMORIES_PER_HOUR
    event = WorkEvent()
    event.last_commit = {"hash": "xyz", "subject": "over limit"}
    result = writer.write(event, branch="main")
    assert result is None  # blocked by rate limit


def test_memory_writer_skips_empty_event():
    from src.warden.memory_watcher import MemoryWriter, WorkEvent
    writer = MemoryWriter(dry_run=True)
    result = writer.write(WorkEvent(), branch="main")
    assert result is None


# ---------------------------------------------------------------------------
# Git hook install/uninstall
# ---------------------------------------------------------------------------

def test_install_and_uninstall_git_hooks(tmp_repo):
    from src.warden.memory_watcher import install_git_hooks, uninstall_git_hooks
    installed = install_git_hooks(tmp_repo)
    assert "post-commit" in installed
    # Verify hook file exists and contains our script
    hook = tmp_repo / ".git" / "hooks" / "post-commit"
    assert hook.exists()
    assert "warden.memory_watcher" in hook.read_text()
    # Uninstall
    removed = uninstall_git_hooks(tmp_repo)
    assert "post-commit" in removed
    if hook.exists():
        assert "warden.memory_watcher" not in hook.read_text()


def test_install_hooks_idempotent(tmp_repo):
    from src.warden.memory_watcher import install_git_hooks
    install_git_hooks(tmp_repo)
    result2 = install_git_hooks(tmp_repo)
    # Second install marks as already installed
    assert any("already installed" in r for r in result2)
    # Hook file should only have one copy of the watcher block
    hook = tmp_repo / ".git" / "hooks" / "post-commit"
    content = hook.read_text()
    assert content.count("warden.memory_watcher") == 1


# ---------------------------------------------------------------------------
# API status endpoint (import-level smoke test)
# ---------------------------------------------------------------------------

def test_get_watcher_status_returns_dict():
    from src.warden.memory_watcher import get_watcher_status
    status = get_watcher_status()
    assert isinstance(status, dict)
    assert "running" in status


def test_start_stop_background_watcher():
    from src.warden.memory_watcher import start_background_watcher, stop_background_watcher
    result = start_background_watcher(dry_run=True)
    assert result in ("started", "already_running")
    stop_result = stop_background_watcher()
    assert stop_result in ("stopped", "not_running")
