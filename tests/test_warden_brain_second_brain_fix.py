"""Tests for the warden_ingest honesty fix + inbox promotion + Obsidian import.

Covers the failure mode this branch fixes: warden_ingest used to delegate to
src.marius.brain_ingest.BrainIngest, which writes to a JSONL store that
brain_search/brain_reindex/brain_list_sources never read — so ingest
returned ok:true for content that was never actually searchable. These tests
assert the new path (src.warden.brain.ingest.ingest_generic, wired through
the warden_ingest MCP tool) is honest: success means searchable, failure is
a real error, and duplicates are detected instead of silently re-copied.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.warden.brain import ingest as brain_ingest
from src.warden.brain import promote as brain_promote
from src.warden.brain.index import fts_search, reindex_sources
from src.warden.brain.vault import init_vault, scan_sources


def _vp(tmp_path: Path) -> Path:
    vp = tmp_path / "vault"
    init_vault(vp)
    return vp


# ---------------------------------------------------------------------------
# ingest_generic: persistence + honesty
# ---------------------------------------------------------------------------

def test_ingest_generic_persists_and_is_searchable(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"

    result = brain_ingest.ingest_generic(
        text="McHarness is Matt's agent operations cockpit with proof gates.",
        title="McHarness Cockpit Notes",
        source_type="manual",
        vault_path=vp,
        index_path=idx,
    )

    assert result["ok"] is True
    assert result["ingested"] is True
    assert result["duplicate"] is False
    assert (vp / result["path"]).exists()

    # The specific claim from the task: honest ok:true means actually
    # searchable, not just written somewhere.
    hits = fts_search("agent operations cockpit", index_path=idx)
    assert any("mcharness cockpit notes" in h.title.lower() for h in hits)


def test_ingest_generic_rejects_unknown_source_type(tmp_path):
    vp = _vp(tmp_path)
    result = brain_ingest.ingest_generic(
        text="hello",
        title="x",
        source_type="not-a-real-type",
        vault_path=vp,
    )
    assert result["ok"] is False
    assert "source_type" in result["error"]
    # Nothing new should have been written (README from init_vault is expected).
    assert [s.path for s in scan_sources(vp) if s.path != "00-inbox/README.md"] == []


def test_ingest_generic_rejects_empty_content(tmp_path):
    vp = _vp(tmp_path)
    result = brain_ingest.ingest_generic(text="   ", title="empty", source_type="manual", vault_path=vp)
    assert result["ok"] is False
    assert [s.path for s in scan_sources(vp) if s.path != "00-inbox/README.md"] == []


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------

def test_ingest_generic_dedupes_identical_content(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    text = "Warden v2 vision alignment: foundation before agents, verified at every layer."

    first = brain_ingest.ingest_generic(text=text, title="Vision A", source_type="manual", vault_path=vp, index_path=idx)
    assert first["ok"] is True and first["duplicate"] is False

    second = brain_ingest.ingest_generic(text=text, title="Vision B (recapture)", source_type="manual", vault_path=vp, index_path=idx)
    assert second["ok"] is True
    assert second["duplicate"] is True
    assert second["duplicate_of"] == first["path"]

    # Only one file exists — the duplicate was not written.
    assert len(list(vp.rglob("*.md"))) == 1 + 1  # +1 for the auto-generated README


def test_ingest_generic_dedupe_ignores_whitespace_differences(tmp_path):
    vp = _vp(tmp_path)
    a = brain_ingest.ingest_generic(text="Line one.\nLine two.", title="A", source_type="manual", vault_path=vp)
    b = brain_ingest.ingest_generic(text="Line one.   Line two.", title="B", source_type="manual", vault_path=vp)
    assert a["duplicate"] is False
    assert b["duplicate"] is True


# ---------------------------------------------------------------------------
# Inbox promotion
# ---------------------------------------------------------------------------

def _write_inbox_note(vp: Path, filename: str, *, title: str, tags: str, body: str) -> Path:
    p = vp / "00-inbox" / filename
    p.write_text(
        f"---\ntitle: {title}\ntags: {tags}\ncreated: 2026-07-07 00:00:00 UTC\nsource: warden\n---\n\n# {title}\n\n{body}\n",
        encoding="utf-8",
    )
    return p


def test_promote_inbox_routes_by_tag(tmp_path):
    vp = _vp(tmp_path)
    _write_inbox_note(vp, "warden-note.md", title="Warden Note", tags="dropzone, warden", body="Warden project content.")
    _write_inbox_note(vp, "profile-note.md", title="Matt Profile", tags="person, profile", body="Who Matt is.")
    _write_inbox_note(vp, "mystery-note.md", title="Mystery", tags="dropzone", body="No routable tag here.")

    result = brain_promote.promote_inbox(vault_path=vp)

    assert result["ok"] is True
    promoted_to = {p["from"]: p["to"] for p in result["promoted"]}
    assert promoted_to["00-inbox/warden-note.md"] == "10-projects/warden-note.md"
    assert promoted_to["00-inbox/profile-note.md"] == "20-people/profile-note.md"
    assert (vp / "10-projects" / "warden-note.md").exists()
    assert (vp / "20-people" / "profile-note.md").exists()

    # Unroutable note stays put rather than being guessed at.
    assert (vp / "00-inbox" / "mystery-note.md").exists()
    assert any(u["path"] == "00-inbox/mystery-note.md" for u in result["unclassified"])


def test_promote_inbox_dedupes_before_routing(tmp_path):
    vp = _vp(tmp_path)
    body = "Same captured article, watched twice by the dropzone watcher."
    _write_inbox_note(vp, "capture-1.md", title="Article", tags="watcher, article", body=body)
    _write_inbox_note(vp, "capture-2.md", title="Article", tags="watcher, article", body=body)

    result = brain_promote.promote_inbox(vault_path=vp)

    assert len(result["promoted"]) == 1
    assert len(result["duplicates"]) == 1
    dup = result["duplicates"][0]
    assert dup["path"] == "00-inbox/capture-2.md"
    assert dup["duplicate_of"] == "00-inbox/capture-1.md"
    assert (vp / "90-archive" / "duplicates" / "capture-2.md").exists()
    assert not (vp / "00-inbox" / "capture-2.md").exists()


def test_promote_inbox_dry_run_moves_nothing(tmp_path):
    vp = _vp(tmp_path)
    _write_inbox_note(vp, "warden-note.md", title="Warden Note", tags="warden", body="content")

    result = brain_promote.promote_inbox(vault_path=vp, dry_run=True)

    assert result["dry_run"] is True
    assert len(result["promoted"]) == 1
    # Nothing actually moved.
    assert (vp / "00-inbox" / "warden-note.md").exists()
    assert not (vp / "10-projects" / "warden-note.md").exists()


# ---------------------------------------------------------------------------
# Obsidian import — read-only against the source vault
# ---------------------------------------------------------------------------

def test_import_obsidian_vault_is_searchable_and_read_only(tmp_path):
    obsidian_src = tmp_path / "obsidian"
    obsidian_src.mkdir()
    unique_phrase = "Warden supervises Claude Code as the harness, not the intelligence"
    note = obsidian_src / "Warden - McHarness.md"
    note.write_text(f"# Warden McHarness\n\n{unique_phrase}.\n", encoding="utf-8")
    original_mtime = note.stat().st_mtime

    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"

    result = brain_ingest.import_obsidian_vault(obsidian_src, vault_path=vp, index_path=idx)

    assert result["ok"] is True
    assert result["scanned"] == 1
    assert result["imported"] == 1
    assert result["duplicates"] == 0

    # Source vault untouched.
    assert note.exists()
    assert note.stat().st_mtime == original_mtime
    assert note.read_text(encoding="utf-8") == f"# Warden McHarness\n\n{unique_phrase}.\n"

    # Imported note is tagged and searchable in the real Warden Brain index —
    # this is the concrete "unique phrase is searchable" proof for the report.
    hits = fts_search("Warden supervises Claude Code as the harness", index_path=idx)
    assert len(hits) >= 1
    assert unique_phrase.split(",")[0] in hits[0].text or "harness" in hits[0].text.lower()

    imported_path = vp / result["imported_notes"][0]["note_path"]
    imported_text = imported_path.read_text(encoding="utf-8")
    assert "obsidian-vault" in imported_text


def test_import_obsidian_vault_dedupes_on_rerun(tmp_path):
    obsidian_src = tmp_path / "obsidian"
    obsidian_src.mkdir()
    (obsidian_src / "note.md").write_text("# Note\n\nSome durable idea.\n", encoding="utf-8")

    vp = _vp(tmp_path)
    first = brain_ingest.import_obsidian_vault(obsidian_src, vault_path=vp)
    second = brain_ingest.import_obsidian_vault(obsidian_src, vault_path=vp)

    assert first["imported"] == 1
    assert second["imported"] == 0
    assert second["duplicates"] == 1


def test_import_obsidian_vault_missing_source(tmp_path):
    vp = _vp(tmp_path)
    result = brain_ingest.import_obsidian_vault(tmp_path / "does-not-exist", vault_path=vp)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# warden_ingest MCP tool — the exact bug report: ok:true must mean searchable
# ---------------------------------------------------------------------------

def _get_tool(name):
    import src.warden.brain_mcp_server as mod
    for tool_name, fn in mod.mcp._tool_manager._tools.items():
        if tool_name == name:
            return fn.fn
    raise KeyError(f"Tool not found: {name}")


def test_warden_ingest_success_is_actually_searchable(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(tmp_path / "vault" / "brain.sqlite3"))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)

    fn = _get_tool("warden_ingest")
    raw = fn(content="Distinctive phrase about verified agent execution loops.", source_type="manual", project="warden")
    payload = json.loads(raw)

    assert payload["ok"] is True
    assert payload["data"]["ingested"] == 1

    search_fn = _get_tool("brain_search")
    search_raw = search_fn(query="verified agent execution loops")
    search_payload = json.loads(search_raw)
    assert search_payload["ok"] is True
    assert search_payload["data"]["count"] >= 1


def test_warden_ingest_rejects_disallowed_path_honestly(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path / "vault"))
    outside = tmp_path / "somewhere-else" / "file.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("content", encoding="utf-8")

    fn = _get_tool("warden_ingest")
    payload = json.loads(fn(path=str(outside), source_type="manual"))

    assert payload["ok"] is False
    assert "not allowed" in payload["error"].lower()


def test_warden_ingest_missing_path_is_a_real_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path / "vault"))
    fn = _get_tool("warden_ingest")
    payload = json.loads(fn(path=str(tmp_path / "vault" / "nope.md"), source_type="manual"))
    assert payload["ok"] is False
    assert "not found" in payload["error"].lower()


def test_warden_ingest_duplicate_is_reported_not_silently_recopied(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(tmp_path / "vault" / "brain.sqlite3"))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    fn = _get_tool("warden_ingest")

    first = json.loads(fn(content="Repeated capture text.", source_type="manual"))
    second = json.loads(fn(content="Repeated capture text.", source_type="manual"))

    assert first["data"]["ingested"] == 1
    assert second["data"]["ingested"] == 0
    assert second["data"]["duplicate"] is True


def test_brain_promote_inbox_tool_registered_and_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path / "vault"))
    from src.warden.brain.vault import init_vault
    init_vault(vault_path=tmp_path / "vault")
    fn = _get_tool("brain_promote_inbox")
    payload = json.loads(fn(dry_run=True))
    assert payload["ok"] is True
    assert payload["data"]["dry_run"] is True


def test_brain_import_obsidian_tool_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path / "vault"))
    src = tmp_path / "obsidian-src"
    src.mkdir()
    (src / "note.md").write_text("# N\n\nSome content.\n", encoding="utf-8")
    fn = _get_tool("brain_import_obsidian")
    payload = json.loads(fn(source_path=str(src)))
    assert payload["ok"] is True
    assert payload["data"]["imported"] == 1
