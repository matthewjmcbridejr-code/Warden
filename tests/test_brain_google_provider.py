"""Tests for Google Brain provider — all network calls mocked."""
import pytest
import os
from unittest.mock import MagicMock
from src.warden.brain import google_provider


@pytest.fixture(autouse=True)
def clean_google_factory():
    google_provider.set_search_client_factory(None)
    yield
    google_provider.set_search_client_factory(None)


def test_google_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    assert google_provider.is_enabled() is False


def test_google_not_configured_without_env(monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_PROJECT_ID", raising=False)
    monkeypatch.delenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", raising=False)
    assert google_provider.is_configured() is False


def test_google_configured_with_env(monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_PROJECT_ID", "my-project")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", "my-store")
    assert google_provider.is_configured() is True


def test_status_returns_setup_required_when_not_configured(monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_PROJECT_ID", raising=False)
    monkeypatch.delenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", raising=False)
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    st = google_provider.status()
    assert st["configured"] is False
    assert len(st["setup_required"]) > 0


def test_status_no_secret_in_response(monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_PROJECT_ID", "my-project")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", "my-store")
    st = google_provider.status()
    text = str(st)
    assert "client_secret" not in text
    assert "access_token" not in text
    assert "refresh_token" not in text


def _make_fake_result(title: str, snippet: str):
    doc = MagicMock()
    doc.id = f"doc-{title}"
    doc.name = f"projects/proj/docs/{title}"
    doc.derived_struct_data = {
        "snippets": [{"snippet": snippet}],
        "title": title,
        "link": f"path/to/{title}.md",
    }
    result = MagicMock()
    result.document = doc
    return result


def test_google_search_mocked(monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_BRAIN_ENABLED", "1")
    monkeypatch.setenv("WARDEN_GOOGLE_PROJECT_ID", "test-proj")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", "test-store")

    fake_results = [
        _make_fake_result("Note A", "Content of note A"),
        _make_fake_result("Note B", "Content of note B"),
    ]

    class FakeClient:
        def search(self, serving_config, query, page_size):
            return fake_results

    google_provider.set_search_client_factory(lambda: FakeClient())
    results = google_provider.search("test query", limit=5)
    assert len(results) == 2
    assert results[0]["title"] == "Note A"
    assert results[0]["provider"] == "google_discovery_engine"
    assert "access_token" not in str(results)


def test_google_search_disabled_returns_empty(monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    results = google_provider.search("anything")
    assert results == []


def test_google_search_not_configured_returns_error(monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_BRAIN_ENABLED", "1")
    monkeypatch.delenv("WARDEN_GOOGLE_PROJECT_ID", raising=False)
    monkeypatch.delenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", raising=False)
    results = google_provider.search("anything")
    assert len(results) == 1
    assert "error" in results[0]


def test_google_answer_mocked(monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_BRAIN_ENABLED", "1")
    monkeypatch.setenv("WARDEN_GOOGLE_PROJECT_ID", "proj")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", "store")

    fake_results = [_make_fake_result("Source Note", "The answer is in the vault.")]

    class FakeClient:
        def search(self, serving_config, query, page_size):
            return fake_results

    google_provider.set_search_client_factory(lambda: FakeClient())
    ans = google_provider.answer("what is the answer?")
    assert ans.google_count == 1
    assert any(c.title == "Source Note" for c in ans.citations)
    assert ans.provider_used == "google_discovery_engine"


def test_serving_config_path_engine(monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_PROJECT_ID", "my-proj")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", "my-store")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_ENGINE_ID", "my-engine")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_SERVING_CONFIG", "default_search")
    cfg = google_provider.get_config()
    path = google_provider._serving_config_path(cfg)
    assert "engines/my-engine" in path
    assert "servingConfigs/default_search" in path


def test_serving_config_path_datastore(monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_PROJECT_ID", "my-proj")
    monkeypatch.setenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", "my-store")
    monkeypatch.delenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_ENGINE_ID", raising=False)
    cfg = google_provider.get_config()
    path = google_provider._serving_config_path(cfg)
    assert "dataStores/my-store" in path
