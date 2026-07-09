"""Tests for automatic wiki curation (src/warden/brain/curator.py).

A fake model gateway stands in for Marius's ProviderGateway so these tests
never touch a real Ollama/OpenRouter endpoint. What's under test is the
curator's own logic: which sources it picks, how it parses model output,
that it never re-distills an already-curated source, and that a bad model
response is reported as a real error rather than silently dropped.

pytest-asyncio isn't part of this project's test dependencies, so async
entry points are driven with asyncio.run() from plain sync test functions
rather than `async def test_...` + a plugin marker.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.warden.brain.curator import _candidate_sources, curate_source, curate_vault
from src.warden.brain.vault import init_vault


def _vp(tmp_path: Path) -> Path:
    vp = tmp_path / "vault"
    init_vault(vp)
    return vp


class FakeGateway:
    """Returns a canned, valid distillation JSON response for every call."""

    def __init__(self, response: dict):
        self.response = response
        self.calls: list[str] = []

    async def chat(self, prompt: str, history=None, brain_enabled=None):
        self.calls.append(prompt)
        return {"response": json.dumps(self.response), "actual": "fake-model:test"}


class BrokenGateway:
    """Returns unparseable garbage — models do misbehave sometimes."""

    async def chat(self, prompt: str, history=None, brain_enabled=None):
        return {"response": "not json at all, sorry"}


def _promoted_note(vp: Path, rel_path: str, title: str, body: str) -> None:
    dest = vp / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"---\ntitle: {title}\ntags: warden\n---\n\n# {title}\n\n{body}\n", encoding="utf-8")


def test_candidate_sources_skips_inbox_and_already_distilled(tmp_path):
    vp = _vp(tmp_path)
    _promoted_note(vp, "10-projects/proof-gates.md", "Proof Gates", "Every agent action needs verifiable proof " * 5)
    _promoted_note(vp, "00-inbox/raw-clip.md", "Raw Clip", "Unprocessed webpage clip " * 5)

    candidates = _candidate_sources(vp, limit=10)
    paths = {c.path for c in candidates}
    assert "10-projects/proof-gates.md" in paths
    assert "00-inbox/raw-clip.md" not in paths


def test_curate_source_writes_wiki_page_from_fake_gateway(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    _promoted_note(
        vp, "10-projects/proof-gates.md", "Proof Gates",
        "Every agent action in Warden needs verifiable proof before it's marked complete. " * 3,
    )
    candidates = _candidate_sources(vp, limit=10)
    assert len(candidates) == 1

    gateway = FakeGateway(response={
        "title": "Proof-Gated Execution",
        "definition": "Agent actions must produce verifiable evidence before being marked done.",
        "principles": ["Never trust a self-reported ok:true"],
        "examples": [],
        "tags": ["warden", "agents"],
        "links": [],
    })

    result = asyncio.run(curate_source(candidates[0], [], gateway=gateway, vault_path=vp, index_path=idx))

    assert result["ok"] is True
    assert result["created"] is True
    assert (vp / "wiki" / "proof-gated-execution.md").exists()
    assert len(gateway.calls) == 1


def test_curate_source_reports_unparseable_response_as_error(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    _promoted_note(vp, "10-projects/note.md", "Note", "Some promoted content worth distilling here. " * 5)
    candidates = _candidate_sources(vp, limit=10)

    result = asyncio.run(curate_source(candidates[0], [], gateway=BrokenGateway(), vault_path=vp, index_path=idx))
    assert result["ok"] is False
    assert "json" in result["error"].lower()


def test_curate_source_only_keeps_links_that_already_exist(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    _promoted_note(vp, "10-projects/note.md", "Note", "Some promoted content worth distilling here. " * 5)
    candidates = _candidate_sources(vp, limit=10)

    gateway = FakeGateway(response={
        "title": "Some Concept",
        "definition": "A concept worth defining.",
        "principles": [],
        "examples": [],
        "tags": [],
        "links": ["Real Existing Page", "Invented Page That Does Not Exist"],
    })

    result = asyncio.run(curate_source(
        candidates[0], ["Real Existing Page"], gateway=gateway, vault_path=vp, index_path=idx,
    ))
    assert result["ok"] is True
    assert result["links"] == ["Real Existing Page"]


def test_curate_vault_dry_run_reports_without_calling_gateway(tmp_path):
    vp = _vp(tmp_path)
    _promoted_note(vp, "10-projects/note.md", "Note", "Some promoted content worth distilling here. " * 5)

    result = asyncio.run(curate_vault(vault_path=vp, limit=10, dry_run=True))
    assert result["dry_run"] is True
    assert result["scanned"] == 1
    assert "10-projects/note.md" in result["would_distill"]


def test_curate_vault_does_not_redistill_same_source_twice(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    _promoted_note(vp, "10-projects/note.md", "Note", "Some promoted content worth distilling " * 5)

    gateway = FakeGateway(response={
        "title": "Distilled Concept",
        "definition": "A definition.",
        "principles": [],
        "examples": [],
        "tags": [],
        "links": [],
    })

    first = asyncio.run(curate_vault(vault_path=vp, index_path=idx, limit=10, gateway=gateway))
    assert len(first["distilled"]) == 1

    second = asyncio.run(curate_vault(vault_path=vp, index_path=idx, limit=10, gateway=gateway))
    assert second["scanned"] == 0
    assert second["distilled"] == []
