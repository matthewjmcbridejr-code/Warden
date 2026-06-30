"""Tests for Warden Brain API endpoints."""
import pytest
from fastapi.testclient import TestClient
from src.warden.app import app


def test_brain_health():
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/brain/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "local" in data
    assert "google" in data


def test_brain_providers():
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/brain/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    ids = [p["provider_id"] for p in data["providers"]]
    assert "local" in ids
    assert "google_discovery_engine" in ids


def test_brain_init_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/init-vault")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["initialized"] is True


def test_brain_reindex(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(tmp_path / "brain.sqlite3"))
    from src.warden.brain.vault import init_vault
    init_vault(vault_path=tmp_path)
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/reindex")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_brain_write_note(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    from src.warden.brain.vault import init_vault
    init_vault(vault_path=tmp_path)
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/write-note",
                       json={"title": "Test Note", "body": "Some content here."})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "path" in data


def test_brain_write_note_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    from src.warden.brain.vault import init_vault
    init_vault(vault_path=tmp_path)
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/write-note",
                       json={"title": "Bad", "body": "x", "filename": "../../etc/passwd"})
    assert resp.status_code == 400


def test_brain_search(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(tmp_path / "brain.sqlite3"))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    from src.warden.brain.vault import init_vault, write_note
    from src.warden.brain.index import reindex_sources
    from src.warden.brain.vault import scan_sources
    init_vault(vault_path=tmp_path)
    write_note("Vault Note", "local brain vault source truth", vault_path=tmp_path)
    reindex_sources(scan_sources(vault_path=tmp_path), index_path=tmp_path / "brain.sqlite3")

    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/brain/search?q=local+brain+vault")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["results"], list)


def test_brain_search_requires_q():
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/brain/search")
    assert resp.status_code == 400


def test_brain_ask(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(tmp_path / "brain.sqlite3"))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    from src.warden.brain.vault import init_vault, write_note
    from src.warden.brain.index import reindex_sources
    from src.warden.brain.vault import scan_sources
    init_vault(vault_path=tmp_path)
    write_note("Brain Source", "the local vault is the source of truth for warden brain", vault_path=tmp_path)
    reindex_sources(scan_sources(vault_path=tmp_path), index_path=tmp_path / "brain.sqlite3")

    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/ask",
                       json={"question": "source truth vault warden brain"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "answer" in data
    assert "citations" in data
    assert "provider_used" in data


def test_brain_no_secret_in_response():
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/brain/health")
    text = resp.text
    assert "access_token" not in text
    assert "client_secret" not in text
    assert "refresh_token" not in text


def test_brain_google_status_not_configured(monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_PROJECT_ID", raising=False)
    monkeypatch.delenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", raising=False)
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/brain/google/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False


def test_brain_mirror_requires_google_enabled(monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/google/mirror",
                       json={"dry_run": True})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
