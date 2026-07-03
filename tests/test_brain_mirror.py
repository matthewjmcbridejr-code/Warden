"""Tests for local→Google mirror engine."""
import pytest
from pathlib import Path
from src.warden.brain.vault import init_vault, write_note, scan_sources
from src.warden.brain.index import reindex_sources
from src.warden.brain import mirror, google_provider


@pytest.fixture(autouse=True)
def clean_pusher():
    mirror.set_document_pusher(None)
    google_provider.set_search_client_factory(None)
    yield
    mirror.set_document_pusher(None)
    google_provider.set_search_client_factory(None)


def _setup(tmp_path):
    init_vault(vault_path=tmp_path)
    write_note("Mirror Test Note",
               "Local Markdown is the source of truth. Google Brain is a mirrored managed index.",
               vault_path=tmp_path)
    sources = scan_sources(vault_path=tmp_path)
    idx = tmp_path / "brain.sqlite3"
    reindex_sources(sources, index_path=idx)
    return tmp_path, idx


def test_mirror_dry_run(tmp_path, monkeypatch):
    vp, idx = _setup(tmp_path)
    result = mirror.mirror_sources(dry_run=True, vault_path=vp, index_path=idx)
    assert result["dry_run"] is True
    assert result["synced"] == 0
    assert len(result["would_sync"]) >= 1
    # No actual push happened
    assert result["errors"] == 0


def test_mirror_mocked_sync(tmp_path):
    vp, idx = _setup(tmp_path)
    pushed_docs = []
    mirror.set_document_pusher(pushed_docs.append)

    result = mirror.mirror_sources(dry_run=False, vault_path=vp, index_path=idx)
    assert result["synced"] >= 1
    assert result["errors"] == 0
    assert len(pushed_docs) >= 1
    # Verify no secrets in pushed document
    for doc in pushed_docs:
        content = str(doc)
        assert "access_token" not in content
        assert "client_secret" not in content


def test_mirror_skips_unchanged(tmp_path):
    vp, idx = _setup(tmp_path)
    pushed = []
    mirror.set_document_pusher(pushed.append)

    result1 = mirror.mirror_sources(dry_run=False, vault_path=vp, index_path=idx)
    assert result1["synced"] >= 1

    result2 = mirror.mirror_sources(dry_run=False, vault_path=vp, index_path=idx)
    assert result2["skipped"] >= 1
    assert result2["synced"] == 0


def test_mirror_resyncs_changed_checksum(tmp_path):
    vp, idx = _setup(tmp_path)
    pushed = []
    mirror.set_document_pusher(pushed.append)

    mirror.mirror_sources(dry_run=False, vault_path=vp, index_path=idx)
    first_count = len(pushed)

    # Modify a note
    notes = list((vp / "00-inbox").glob("*.md"))
    notes[0].write_text(notes[0].read_text() + "\nUpdated content.")

    result = mirror.mirror_sources(dry_run=False, vault_path=vp, index_path=idx)
    assert len(pushed) > first_count  # at least one re-push


def test_mirror_redacts_secrets(tmp_path):
    vp, idx = _setup(tmp_path)
    # Write note with secret-looking content
    write_note("Secret Test", "api_key=TOPSECRETVALUE999", vault_path=vp)
    reindex_sources(scan_sources(vault_path=vp), index_path=idx)

    pushed = []
    mirror.set_document_pusher(pushed.append)
    mirror.mirror_sources(dry_run=False, vault_path=vp, index_path=idx)

    all_content = str(pushed)
    assert "TOPSECRETVALUE999" not in all_content


def test_mirror_status_empty(tmp_path):
    idx = tmp_path / "brain.sqlite3"
    result = mirror.mirror_status(index_path=idx)
    assert "records" in result
    assert "counts" in result


def test_mirror_status_after_sync(tmp_path):
    vp, idx = _setup(tmp_path)
    pushed = []
    mirror.set_document_pusher(pushed.append)
    mirror.mirror_sources(dry_run=False, vault_path=vp, index_path=idx)

    result = mirror.mirror_status(index_path=idx)
    assert "synced" in result["counts"]
    assert result["counts"]["synced"] >= 1
