"""Tests for the Warden Model Gateway: policy router, context budget, traces."""
from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


# ── Policy router tests ───────────────────────────────────────────────────────

def test_greeting_routes_local():
    from src.warden.gateway.policy import route
    d = route("hi")
    assert d.alias == "warden-local"
    assert d.confidence >= 0.90
    assert d.classifier_used == "rules"


def test_code_task_routes_code():
    from src.warden.gateway.policy import route
    d = route("fix the bug in context_budget.py")
    assert d.alias == "warden-code"
    assert d.confidence >= 0.80


def test_architecture_routes_deep():
    from src.warden.gateway.policy import route
    d = route("should we use Redis or in-memory cache — trade-offs?")
    assert d.alias == "warden-deep"


def test_status_routes_fast():
    from src.warden.gateway.policy import route
    d = route("where we at with the gateway sprint?")
    assert d.alias == "warden-fast"


def test_privacy_guard_blocks_free():
    """Content with API key patterns must never reach warden-free."""
    from src.warden.gateway.policy import route
    d = route("demo example GROQ_API_KEY=sk-secret show me")
    assert d.alias != "warden-free"
    assert d.privacy == "private"


def test_force_alias_respected():
    from src.warden.gateway.policy import route
    d = route("anything", force_alias="warden-deep")
    assert d.alias == "warden-deep"
    assert d.classifier_used == "forced"


def test_likely_tools_git():
    from src.warden.gateway.policy import route
    d = route("show me the git log for the last 5 commits")
    assert "git_log" in d.likely_tools


def test_likely_tools_memory():
    from src.warden.gateway.policy import route
    d = route("recall the memory about the gateway sprint")
    assert "recall_memories" in d.likely_tools


def test_likely_tools_web():
    from src.warden.gateway.policy import route
    d = route("search the web for LiteLLM proxy docs")
    assert "web_search" in d.likely_tools


def test_private_content_detection():
    from src.warden.gateway.policy import _is_private
    assert _is_private("# Warden Memory Context")
    assert _is_private("sk-or-abcdef12345")
    assert _is_private("TAVILY_API_KEY=xyz")
    assert not _is_private("hello world")


def test_token_estimate():
    from src.warden.gateway.policy import _estimate_tokens
    t = _estimate_tokens("a" * 400)
    assert t == 100


# ── Context budget tests ──────────────────────────────────────────────────────

def test_budget_keeps_high_relevance():
    from src.warden.gateway.context_budget import build_budget, ContextItem
    memories = [
        {"content": "gateway sprint started 2025-06", "relevance": 0.9},
        {"content": "unrelated note about groceries", "relevance": 0.1},
    ]
    result = build_budget(
        alias="warden-fast",
        query="where are we with the gateway sprint?",
        memories=memories,
        git_context=None,
        github_items=[],
        tool_outputs=[],
        conversation=[],
        system_prompt=None,
    )
    inspection = result.items
    kept = [i for i in inspection if i.status == "kept"]
    dropped = [i for i in inspection if i.status == "dropped"]
    assert any("gateway" in i.content for i in kept)


def test_budget_respects_alias_limit():
    from src.warden.gateway.context_budget import build_budget, _ALIAS_BUDGETS
    big_text = "word " * 2000  # ~2000 tokens worth
    result = build_budget(
        alias="warden-local",
        query="summarize",
        memories=[{"content": big_text, "relevance": 0.9}],
        git_context=None,
        github_items=[],
        tool_outputs=[],
        conversation=[],
        system_prompt=None,
    )
    assert result.total_after <= _ALIAS_BUDGETS["warden-local"]


def test_budget_inspect_returns_list():
    from src.warden.gateway.context_budget import build_budget, inspect
    result = build_budget(
        alias="warden-fast",
        query="status update",
        memories=[{"content": "sprint notes", "relevance": 0.7}],
        git_context="main branch, 3 ahead",
        github_items=[],
        tool_outputs=[],
        conversation=[],
        system_prompt=None,
    )
    rows = inspect(result)
    assert isinstance(rows, list)
    for row in rows:
        assert "source" in row
        assert "status" in row
        assert row["status"] in ("kept", "dropped", "compressed")


# ── Trace storage tests ───────────────────────────────────────────────────────

def test_trace_record_and_recent():
    from src.warden.gateway import traces
    with tempfile.TemporaryDirectory() as tmp:
        test_file = Path(tmp) / "traces.jsonl"
        with patch.object(traces, "TRACE_FILE", test_file):
            t = traces.GatewayTrace(
                trace_id="gt_test000001",
                task_preview="fix the bug",
                alias="warden-code",
                provider="groq",
                model="llama-3.3-70b",
                classifier_used="rules",
                tools_called=[],
                fallback_used=False,
                tokens_before=200,
                tokens_after=180,
                privacy="private",
                openrouter_free_blocked=False,
                privacy_block_reason="",
                status="ok",
                elapsed_ms=420,
            )
            traces.record(t)
            recent = traces.recent(limit=10)
            assert len(recent) == 1
            assert recent[0]["alias"] == "warden-code"
            assert recent[0]["trace_id"] == "gt_test000001"


def test_trace_prune_to_max():
    from src.warden.gateway import traces
    with tempfile.TemporaryDirectory() as tmp:
        test_file = Path(tmp) / "traces.jsonl"
        with patch.object(traces, "TRACE_FILE", test_file), \
             patch.object(traces, "MAX_TRACES", 5):
            for i in range(10):
                t = traces.GatewayTrace(
                    trace_id=f"gt_{i:010d}",
                    task_preview=f"task {i}",
                    alias="warden-fast",
                    provider="groq",
                    model="llama-3.1-8b",
                    classifier_used="rules",
                    tools_called=[],
                    fallback_used=False,
                    tokens_before=100,
                    tokens_after=90,
                    privacy="private",
                    openrouter_free_blocked=False,
                    privacy_block_reason="",
                    status="ok",
                    elapsed_ms=100,
                )
                traces.record(t)
            lines = test_file.read_text().splitlines()
            assert len(lines) <= 5


def test_make_trace_id_format():
    from src.warden.gateway.traces import make_trace_id
    tid = make_trace_id()
    assert tid.startswith("gt_")
    assert len(tid) == 13  # "gt_" + 10 hex chars


# ── Alias definitions tests ───────────────────────────────────────────────────

def test_all_aliases_present():
    from src.warden.gateway.aliases import ALIAS_DEFS, ALIAS_NAMES
    expected = {"warden-local", "warden-fast", "warden-free", "warden-code", "warden-deep", "warden-embed"}
    assert set(ALIAS_NAMES) == expected


def test_alias_schema():
    from src.warden.gateway.aliases import ALIAS_DEFS
    required_fields = {"label", "description", "primary_provider", "privacy", "max_context_tokens", "cost_tier"}
    for name, defn in ALIAS_DEFS.items():
        missing = required_fields - set(defn.keys())
        assert not missing, f"{name} missing fields: {missing}"


def test_warden_local_is_always_private():
    from src.warden.gateway.aliases import ALIAS_DEFS
    assert ALIAS_DEFS["warden-local"]["privacy"] == "private"
    assert ALIAS_DEFS["warden-local"]["cloud_allowed"] is False


def test_warden_free_openrouter_flag():
    from src.warden.gateway.aliases import ALIAS_DEFS
    assert ALIAS_DEFS["warden-free"]["openrouter_free_allowed"] is True


# ── Provider check (unit — no network) ───────────────────────────────────────

def test_provider_check_structure():
    from src.warden.gateway import providers
    with patch.object(providers, "_ping", return_value=(False, 0)), \
         patch.object(providers, "_key_present", return_value=False):
        results = providers.check_all()
    names = {r["provider"] for r in results}
    assert "Ollama" in names
    assert "Groq" in names
    assert "LiteLLM Gateway" in names
    for r in results:
        assert "status" in r
        assert "key_configured" in r


def test_ollama_reachable_shows_models():
    from src.warden.gateway import providers
    import json
    fake_tags = json.dumps({"models": [{"name": "qwen3:0.6b"}, {"name": "gemma3:1b"}]}).encode()

    class FakeResp:
        def read(self): return fake_tags
        def __enter__(self): return self
        def __exit__(self, *a): pass

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        results = providers.check_all()
    ollama = next(r for r in results if r["provider"] == "Ollama")
    assert ollama["status"] == "reachable"
    assert ollama["models_available"] == 2
