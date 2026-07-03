"""Tests for SQLite FTS5 brain index."""
import pytest
from pathlib import Path
from src.warden.brain.vault import init_vault, write_note, scan_sources
from src.warden.brain.index import reindex_sources, fts_search, count_sources, list_sources


def _setup_vault(tmp_path):
    init_vault(vault_path=tmp_path)
    write_note("Warden Brain Decision",
               "Warden Brain uses the local Markdown vault as the source of truth. "
               "Google Brain is a mirrored managed index.",
               vault_path=tmp_path)
    write_note("Connector Setup",
               "OAuth connectors require a client_id and client_secret configured through the Warden UI.",
               vault_path=tmp_path)


def test_reindex_adds_sources(tmp_path):
    _setup_vault(tmp_path)
    sources = scan_sources(vault_path=tmp_path)
    idx = tmp_path / "brain.sqlite3"
    result = reindex_sources(sources, index_path=idx)
    assert result["added"] >= 2
    assert result["errors"] == 0


def test_reindex_skips_unchanged(tmp_path):
    _setup_vault(tmp_path)
    sources = scan_sources(vault_path=tmp_path)
    idx = tmp_path / "brain.sqlite3"
    reindex_sources(sources, index_path=idx)
    result2 = reindex_sources(sources, index_path=idx)
    assert result2["skipped"] >= 2
    assert result2["added"] == 0


def test_fts_search_finds_content(tmp_path):
    _setup_vault(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    reindex_sources(scan_sources(vault_path=tmp_path), index_path=idx)
    chunks = fts_search("source truth vault", index_path=idx)
    assert len(chunks) >= 1
    assert any("vault" in c.text.lower() for c in chunks)


def test_fts_search_empty_query(tmp_path):
    idx = tmp_path / "brain.sqlite3"
    chunks = fts_search("", index_path=idx)
    assert chunks == []


def test_fts_search_no_results(tmp_path):
    _setup_vault(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    reindex_sources(scan_sources(vault_path=tmp_path), index_path=idx)
    chunks = fts_search("xyzzyplonk", index_path=idx)
    assert chunks == []


def test_count_sources(tmp_path):
    _setup_vault(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    reindex_sources(scan_sources(vault_path=tmp_path), index_path=idx)
    n = count_sources(index_path=idx)
    assert n >= 2


def test_list_sources(tmp_path):
    _setup_vault(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    reindex_sources(scan_sources(vault_path=tmp_path), index_path=idx)
    sources = list_sources(index_path=idx)
    assert len(sources) >= 2
    assert all("path" in s and "title" in s for s in sources)
