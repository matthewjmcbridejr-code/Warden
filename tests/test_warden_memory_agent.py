"""Tests for Warden Memory Chat Agent."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# MemoryContext
# ---------------------------------------------------------------------------

def test_memory_context_empty_source_labels():
    from src.warden.memory_agent import MemoryContext
    ctx = MemoryContext()
    assert ctx.source_labels() == []


def test_memory_context_source_labels_populated():
    from src.warden.memory_agent import MemoryContext
    ctx = MemoryContext(
        git_log=["abc123 fix: something"],
        shell_commands=["pytest tests/"],
        browser_visits=[{"url": "https://github.com/foo", "title": "foo", "visited_at": ""}],
        board_tasks=[{"title": "Do stuff", "status": "working"}],
        recent_memories=[{"kind": "proof", "summary": "Tests pass"}],
        current_branch="main",
    )
    labels = ctx.source_labels()
    assert "git" in labels
    assert "shell" in labels
    assert "chrome" in labels
    assert "board" in labels
    assert "memories" in labels


def test_memory_context_to_context_block_contains_sections():
    from src.warden.memory_agent import MemoryContext
    ctx = MemoryContext(
        current_branch="feat/test",
        git_log=["abc123 feat: add thing"],
        shell_commands=["git commit -m 'test'"],
        browser_visits=[{"url": "https://github.com/foo", "title": "GitHub Foo", "visited_at": "2026-06-27T00:00:00Z"}],
        board_tasks=[{"title": "Write tests", "status": "working", "agent": "codex"}],
        recent_memories=[{"kind": "proof", "summary": "Tests all passing", "source": "memory_watcher"}],
        gathered_at="2026-06-27 23:00 UTC",
    )
    block = ctx.to_context_block()
    assert "feat/test" in block
    assert "feat: add thing" in block
    assert "git commit" in block
    assert "GitHub Foo" in block
    assert "Write tests" in block
    assert "Tests all passing" in block
    assert "Git State" in block
    assert "Browser Activity" in block
    assert "Shell Commands" in block


# ---------------------------------------------------------------------------
# _fallback_structured_answer
# ---------------------------------------------------------------------------

def test_fallback_answer_no_data():
    from src.warden.memory_agent import MemoryContext, _fallback_structured_answer
    ctx = MemoryContext(gathered_at="2026-06-27 23:00 UTC")
    answer = _fallback_structured_answer("What did I work on?", ctx)
    assert "No activity data" in answer or "memory watcher" in answer.lower()


def test_fallback_answer_with_commits():
    from src.warden.memory_agent import MemoryContext, _fallback_structured_answer
    ctx = MemoryContext(
        current_branch="main",
        git_log=["abc123 feat: add memory agent"],
        gathered_at="2026-06-27 23:00 UTC",
    )
    answer = _fallback_structured_answer("What did I commit?", ctx)
    assert "feat: add memory agent" in answer
    assert "main" in answer


# ---------------------------------------------------------------------------
# chat() — mocked Ollama
# ---------------------------------------------------------------------------

def test_chat_calls_ollama_and_returns_reply():
    from src.warden.memory_agent import chat

    mock_context = MagicMock()
    mock_context.to_context_block.return_value = "# Context Block"
    mock_context.source_labels.return_value = ["git", "shell"]
    mock_context.current_branch = "main"
    mock_context.git_log = ["abc fix: test"]
    mock_context.shell_commands = ["pytest"]
    mock_context.browser_visits = []
    mock_context.board_tasks = []
    mock_context.recent_memories = []
    mock_context.gathered_at = "2026-06-27 23:00 UTC"

    with patch("src.warden.memory_agent.gather_context", return_value=mock_context), \
         patch("src.warden.memory_agent._ollama_chat", return_value="You've been writing tests.") as mock_llm:

        result = chat("What did I do?")

    mock_llm.assert_called_once()
    assert result.reply == "You've been writing tests."
    assert result.fallback is False
    assert "git" in result.sources


def test_chat_falls_back_when_ollama_fails():
    from src.warden.memory_agent import chat

    mock_context = MagicMock()
    mock_context.to_context_block.return_value = "# Context"
    mock_context.source_labels.return_value = ["git"]
    mock_context.current_branch = "main"
    mock_context.git_log = ["abc fix: x"]
    mock_context.shell_commands = []
    mock_context.browser_visits = []
    mock_context.board_tasks = []
    mock_context.recent_memories = []
    mock_context.gathered_at = "2026-06-27 23:00 UTC"

    with patch("src.warden.memory_agent.gather_context", return_value=mock_context), \
         patch("src.warden.memory_agent._ollama_chat", side_effect=ConnectionError("ollama down")):

        result = chat("What did I do?")

    assert result.fallback is True
    assert result.model_used == "fallback"
    assert "main" in result.reply  # fallback includes branch


def test_chat_carries_history():
    from src.warden.memory_agent import chat

    captured_messages = []

    def fake_ollama(messages, model, **kwargs):
        captured_messages.extend(messages)
        return "Great question based on history."

    mock_context = MagicMock()
    mock_context.to_context_block.return_value = "# ctx"
    mock_context.source_labels.return_value = []
    mock_context.current_branch = "main"
    mock_context.git_log = []
    mock_context.shell_commands = []
    mock_context.browser_visits = []
    mock_context.board_tasks = []
    mock_context.recent_memories = []
    mock_context.gathered_at = "2026-06-27"

    history = [
        {"role": "user", "content": "Previous question"},
        {"role": "assistant", "content": "Previous answer"},
    ]

    with patch("src.warden.memory_agent.gather_context", return_value=mock_context), \
         patch("src.warden.memory_agent._ollama_chat", side_effect=fake_ollama):
        result = chat("Follow-up question", history=history)

    roles = [m["role"] for m in captured_messages]
    contents = [m["content"] for m in captured_messages]
    assert "Previous question" in contents
    assert "Previous answer" in contents
    assert "Follow-up question" in contents
    assert result.reply == "Great question based on history."


# ---------------------------------------------------------------------------
# ChatResponse context_snapshot
# ---------------------------------------------------------------------------

def test_chat_returns_context_snapshot():
    from src.warden.memory_agent import chat

    mock_context = MagicMock()
    mock_context.to_context_block.return_value = "# ctx"
    mock_context.source_labels.return_value = ["git"]
    mock_context.current_branch = "feat/x"
    mock_context.git_log = ["a", "b", "c"]
    mock_context.shell_commands = ["pytest"]
    mock_context.browser_visits = []
    mock_context.board_tasks = [{"title": "t", "status": "working"}]
    mock_context.recent_memories = [{"kind": "proof", "summary": "ok"}]
    mock_context.gathered_at = "2026-06-27 23:00 UTC"

    with patch("src.warden.memory_agent.gather_context", return_value=mock_context), \
         patch("src.warden.memory_agent._ollama_chat", return_value="summary"):
        result = chat("summarize")

    snap = result.context_snapshot
    assert snap["branch"] == "feat/x"
    assert snap["commits"] == 3
    assert snap["shell_commands"] == 1
    assert snap["board_tasks"] == 1
    assert snap["memories"] == 1
