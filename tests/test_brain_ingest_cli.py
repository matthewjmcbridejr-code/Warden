"""Tests for warden.brain_ingest_cli — the daily Obsidian/repo ingest timer.

This CLI is what warden-brain-ingest-obsidian.timer actually runs every
night. It had the same bug as the warden_ingest MCP tool: it delegated to
src.marius.brain_ingest.BrainIngest, a JSONL store that brain_search never
reads, so the nightly "N ingested" log was never actually searchable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.warden.brain.index import fts_search
from src.warden.brain.vault import init_vault


def _run_cli(argv, monkeypatch):
    from src.warden import brain_ingest_cli
    monkeypatch.setattr(sys, "argv", ["brain_ingest_cli"] + argv)
    brain_ingest_cli.main()


def test_cli_ingest_is_actually_searchable(tmp_path, monkeypatch, capsys):
    vp = tmp_path / "vault"
    idx = tmp_path / "vault" / "brain.sqlite3"
    init_vault(vp)
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(vp))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(idx))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)

    src_dir = tmp_path / "obsidian-src"
    src_dir.mkdir()
    (src_dir / "note.md").write_text(
        "A durable claim about verified agent memory architecture.",
        encoding="utf-8",
    )

    _run_cli(["--path", str(src_dir), "--project", "personal", "--source-type", "obsidian", "--max-files", "10"], monkeypatch)

    out = capsys.readouterr().out
    assert "1 ingested" in out

    hits = fts_search("verified agent memory architecture", index_path=idx)
    assert len(hits) >= 1


def test_cli_reports_duplicates_on_rerun(tmp_path, monkeypatch, capsys):
    vp = tmp_path / "vault"
    init_vault(vp)
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(vp))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(vp / "brain.sqlite3"))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.md").write_text("Same content every night.", encoding="utf-8")

    _run_cli(["--path", str(src_dir), "--source-type", "doc"], monkeypatch)
    capsys.readouterr()
    _run_cli(["--path", str(src_dir), "--source-type", "doc"], monkeypatch)
    out = capsys.readouterr().out

    assert "0 ingested, 1 skipped" in out
    assert "duplicate of" in out
