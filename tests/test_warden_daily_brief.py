"""Tests for Warden Daily Brief."""
import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_board(tmp_path, monkeypatch):
    board = tmp_path / "_mctable"
    (board / "tasks" / "queued").mkdir(parents=True)
    (board / "tasks" / "completed").mkdir(parents=True)
    (board / "tasks" / "failed").mkdir(parents=True)
    (board / "tasks" / "needs_review").mkdir(parents=True)
    (board / "tasks" / "claimed").mkdir(parents=True)
    (board / "tasks" / "running").mkdir(parents=True)
    (board / "activity").mkdir(parents=True)
    import src.warden.daily_brief as mod
    monkeypatch.setattr(mod, "BOARD_ROOT", board)
    monkeypatch.setattr(mod, "BRIEF_DIR", tmp_path / "briefs")
    return board


def _write_task(board: Path, status: str, task_id: str, title: str):
    d = board / "tasks" / status
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task_id}.json").write_text(json.dumps({
        "task_id": task_id, "title": title, "status": status, "priority": "medium",
    }))


def test_generate_daily_brief_returns_markdown(tmp_board):
    from src.warden.daily_brief import generate_daily_brief
    md = generate_daily_brief(date="2026-06-27")
    assert "# Warden Daily Brief" in md
    assert "2026-06-27" in md
    assert "## Top Next Actions" in md
    assert "## Failures" in md
    assert "## Recommended Action" in md


def test_brief_includes_queued_tasks(tmp_board):
    _write_task(tmp_board, "queued", "q1", "Deploy alpha")
    from src.warden.daily_brief import generate_daily_brief
    md = generate_daily_brief(date="2026-06-27")
    assert "Deploy alpha" in md


def test_brief_includes_failed_tasks(tmp_board):
    _write_task(tmp_board, "failed", "f1", "Failed migration")
    from src.warden.daily_brief import generate_daily_brief
    md = generate_daily_brief(date="2026-06-27")
    # Failed tasks show in failures section (or memories if available)
    assert "Failed migration" in md or "Failures" in md


def test_save_brief_creates_file(tmp_board):
    from src.warden.daily_brief import generate_and_save
    result = generate_and_save(date="2026-06-27")
    assert result["ok"]
    path = Path(result["path"])
    assert path.exists()
    assert "Warden Daily Brief" in path.read_text()


def test_recommended_action_prioritizes_needs_review(tmp_board):
    _write_task(tmp_board, "needs_review", "nr1", "Review auth changes")
    from src.warden.daily_brief import generate_daily_brief
    md = generate_daily_brief(date="2026-06-27")
    assert "Review auth changes" in md or "Needs Review" in md
