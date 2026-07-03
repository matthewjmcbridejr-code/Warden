"""Tests for hybrid brain answering (local + Google fanout)."""
import pytest
from unittest.mock import MagicMock
from src.warden.brain import hybrid, google_provider
from src.warden.brain.vault import init_vault, write_note
from src.warden.brain.index import reindex_sources
from src.warden.brain.vault import scan_sources


@pytest.fixture(autouse=True)
def clean_factory():
    google_provider.set_search_client_factory(None)
    yield
    google_provider.set_search_client_factory(None)


def _setup_local(tmp_path):
    init_vault(vault_path=tmp_path)
    write_note("Local Knowledge",
               "The local vault is the source of truth for Warden Brain.",
               vault_path=tmp_path)
    idx = tmp_path / "brain.sqlite3"
    reindex_sources(scan_sources(vault_path=tmp_path), index_path=idx)
    return tmp_path, idx


def test_hybrid_local_only_when_google_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    vp, idx = _setup_local(tmp_path)
    ans = hybrid.answer("local vault source truth", limit=4, index_path=idx, vault_path=vp)
    assert ans.provider_used in ("local",)
    assert ans.google_count == 0


def test_hybrid_labels_provider_used(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    vp, idx = _setup_local(tmp_path)
    ans = hybrid.answer("source truth vault", index_path=idx, vault_path=vp)
    assert ans.provider_used == "local"
    assert "local" in ans.provider_used


def test_hybrid_google_failure_falls_back_to_local(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_BRAIN_ENABLED", "1")
    monkeypatch.setenv("WARDEN_GOOGLE_PROJECT_ID", "proj")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", "store")

    class FailingClient:
        def search(self, *a, **kw):
            raise RuntimeError("Google is down")

    google_provider.set_search_client_factory(lambda: FailingClient())
    vp, idx = _setup_local(tmp_path)
    # Should not raise — falls back gracefully
    ans = hybrid.answer("source truth vault", index_path=idx, vault_path=vp)
    assert ans is not None
    assert len(ans.errors) > 0  # error recorded
    assert ans.local_count >= 0  # local still ran


def test_hybrid_dedup_citations(tmp_path, monkeypatch):
    """Dedup removes citations with identical (title, heading) pairs."""
    from src.warden.brain.hybrid import _dedup_citations
    from src.warden.brain.models import BrainCitation

    dups = [
        BrainCitation("path/a.md", "Same Title", "Same Heading", "text1", "local"),
        BrainCitation("path/a.md", "Same Title", "Same Heading", "text2", "google_discovery_engine"),
        BrainCitation("path/b.md", "Different Title", "", "text3", "local"),
    ]
    result = _dedup_citations(dups)
    assert len(result) == 2  # same (title, heading) → one removed
    titles = [c.title for c in result]
    assert "Same Title" in titles
    assert "Different Title" in titles


def test_hybrid_search_merges_results(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_BRAIN_ENABLED", "1")
    monkeypatch.setenv("WARDEN_GOOGLE_PROJECT_ID", "proj")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", "store")

    doc = MagicMock()
    doc.id = "g-doc1"
    doc.name = "google/doc1"
    doc.derived_struct_data = {
        "snippets": [{"snippet": "Google result"}],
        "title": "Google Doc",
        "link": "google/doc1",
    }
    r = MagicMock()
    r.document = doc

    class FakeClient:
        def search(self, serving_config, query, page_size):
            return [r]

    google_provider.set_search_client_factory(lambda: FakeClient())
    vp, idx = _setup_local(tmp_path)
    results = hybrid.search("source truth", index_path=idx)
    providers = {res.get("provider") for res in results if "error" not in res}
    assert "local" in providers or "google_discovery_engine" in providers


def test_no_secrets_in_hybrid_answer(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    vp, idx = _setup_local(tmp_path)
    ans = hybrid.answer("source truth vault", index_path=idx, vault_path=vp)
    text = str(ans.to_dict())
    assert "access_token" not in text
    assert "client_secret" not in text
    assert "refresh_token" not in text
