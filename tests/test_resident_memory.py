"""Memory adapter tests (mocked underlying stores), capped result count."""
from unittest.mock import patch

from src.warden.resident.memory import DEFAULT_SEARCH_LIMIT, MemoryAdapter


def _fake_memories(n):
    return [
        {"memory_id": f"mem-{i}", "summary": f"summary {i}", "created_at": f"2026-01-0{i%9+1}", "kind": "context"}
        for i in range(n)
    ]


def test_search_caps_results_to_default_limit():
    adapter = MemoryAdapter()
    with patch("src.warden.memory_agent._recent_memories", return_value=_fake_memories(20)):
        results = adapter.search("warden")
    assert len(results) <= DEFAULT_SEARCH_LIMIT


def test_search_respects_smaller_limit():
    adapter = MemoryAdapter()
    with patch("src.warden.memory_agent._recent_memories", return_value=_fake_memories(20)):
        results = adapter.search("warden", limit=2)
    assert len(results) == 2


def test_search_results_have_source_id_and_created_at():
    adapter = MemoryAdapter()
    with patch("src.warden.memory_agent._recent_memories", return_value=_fake_memories(3)):
        results = adapter.search("warden")
    for r in results:
        assert r.source_id
        assert r.created_at


def test_search_handles_underlying_failure_gracefully():
    adapter = MemoryAdapter()
    with patch("src.warden.memory_agent._recent_memories", side_effect=RuntimeError("boom")):
        results = adapter.search("warden")
    assert results == []


def test_recent_caps_results():
    adapter = MemoryAdapter()
    fake_workstream = [
        {"memory_id": f"m{i}", "summary": f"s{i}", "updated_at": "2026-01-01", "kind": "proof"}
        for i in range(20)
    ]
    with patch("src.warden.personal_memory.get_workstream", return_value=fake_workstream[:DEFAULT_SEARCH_LIMIT]):
        results = adapter.recent()
    assert len(results) <= DEFAULT_SEARCH_LIMIT


def test_remember_saves_note():
    adapter = MemoryAdapter()
    with patch("marius.memory.save_fact") as mock_save:
        result = adapter.remember("test note")
    mock_save.assert_called_once()
    assert result.kind == "note"


def test_remember_handles_failure_gracefully():
    adapter = MemoryAdapter()
    with patch("marius.memory.save_fact", side_effect=RuntimeError("no db")):
        result = adapter.remember("test note")
    assert result.kind == "note_failed"
