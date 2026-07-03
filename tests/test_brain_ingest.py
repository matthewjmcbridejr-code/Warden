"""Tests for Warden Brain ingest module."""
import pytest
from unittest.mock import patch, MagicMock
from src.warden.brain import ingest as brain_ingest
from src.warden.brain.vault import init_vault, scan_sources


def test_extractive_summary_short():
    text = "Hello world."
    assert brain_ingest._extractive_summary(text) == "Hello world."


def test_extractive_summary_truncates():
    text = "A" * 600
    result = brain_ingest._extractive_summary(text, max_chars=100)
    assert len(result) <= 200  # may extend to sentence boundary


def test_infer_tags_youtube():
    tags = brain_ingest._infer_tags("https://youtube.com/watch?v=abc", "youtube")
    assert "youtube" in tags
    assert "watcher" in tags
    assert "video" in tags


def test_infer_tags_github():
    tags = brain_ingest._infer_tags("https://github.com/user/repo", "webpage")
    assert "github" in tags
    assert "code" in tags


def test_stable_filename_format():
    fname = brain_ingest._stable_filename("https://example.com/article", "webpage")
    assert fname.startswith("webpage-")
    assert fname.endswith(".md")
    # hash is 8 hex chars
    assert len(fname) > 20


def test_ingest_webpage(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    result = brain_ingest.ingest_webpage(
        url="https://example.com/article",
        title="Test Article",
        content_text="This is the article body about Python programming.",
        vault_path=tmp_path,
        index_path=tmp_path / "brain.sqlite3",
    )
    assert result["ok"] is True
    assert result["source_type"] == "webpage"
    assert "watcher" in result["tags"]
    assert result["note_path"] is not None


def test_ingest_selection(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    result = brain_ingest.ingest_selection(
        url="https://example.com/article",
        title="Test Article",
        selected_text="Key insight: Python is a great language.",
        vault_path=tmp_path,
        index_path=tmp_path / "brain.sqlite3",
    )
    assert result["ok"] is True
    assert result["source_type"] == "selection"
    assert "selection" in result["tags"]
    assert "Selection:" in result["title"]


def test_ingest_youtube_no_transcript(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    result = brain_ingest.ingest_youtube(
        url="https://youtube.com/watch?v=dQw4w9WgXcQ",
        title="Rick Astley",
        channel="Rick",
        vault_path=tmp_path,
        index_path=tmp_path / "brain.sqlite3",
    )
    assert result["ok"] is True
    assert result["source_type"] == "youtube"
    assert "youtube" in result["tags"]
    assert result["title"] == "Rick Astley"


def test_ingest_youtube_with_transcript(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    result = brain_ingest.ingest_youtube(
        url="https://youtube.com/watch?v=dQw4w9WgXcQ",
        title="Python Tutorial",
        transcript="In this video we cover variables loops and functions in Python.",
        vault_path=tmp_path,
        index_path=tmp_path / "brain.sqlite3",
    )
    assert result["ok"] is True
    assert result["transcript_chars"] > 0


def test_ingest_pdf_url_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    # URL will fail to fetch (not a real PDF) — should still create a note
    result = brain_ingest.ingest_pdf(
        url="https://example.com/paper.pdf",
        title="Test PDF",
        vault_path=tmp_path,
        index_path=tmp_path / "brain.sqlite3",
    )
    assert result["ok"] is True
    assert result["source_type"] == "pdf"
    assert "pdf" in result["tags"]


def test_extract_youtube_id():
    assert brain_ingest._extract_youtube_id("https://youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert brain_ingest._extract_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert brain_ingest._extract_youtube_id("https://example.com") is None


def test_fetch_youtube_transcript_bad_url():
    result = brain_ingest.fetch_youtube_transcript("https://notayoutube.com/video")
    assert "error" in result


def test_no_secrets_in_ingest_result(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    result = brain_ingest.ingest_webpage(
        url="https://example.com",
        title="Test",
        content_text="Normal content without secrets.",
        vault_path=tmp_path,
        index_path=tmp_path / "brain.sqlite3",
    )
    text = str(result)
    assert "access_token" not in text
    assert "client_secret" not in text
    assert "refresh_token" not in text


def test_ingest_api_webpage(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(tmp_path / "brain.sqlite3"))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    from fastapi.testclient import TestClient
    from src.warden.app import app
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/ingest", json={
        "url": "https://example.com/article",
        "title": "Example Article",
        "source_type": "webpage",
        "content_text": "Python is great for scripting and data science.",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source_type"] == "webpage"


def test_ingest_api_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(tmp_path / "brain.sqlite3"))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    from fastapi.testclient import TestClient
    from src.warden.app import app
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/ingest", json={
        "url": "https://example.com/article",
        "title": "Example Article",
        "source_type": "selection",
        "selected_text": "The key insight is that Python has great libraries.",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_ingest_api_selection_missing_text(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    init_vault(vault_path=tmp_path)
    from fastapi.testclient import TestClient
    from src.warden.app import app
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/ingest", json={
        "url": "https://example.com",
        "source_type": "selection",
    })
    assert resp.status_code == 400


def test_ingest_api_youtube(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(tmp_path / "brain.sqlite3"))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    from fastapi.testclient import TestClient
    from src.warden.app import app
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/ingest", json={
        "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "Rick Astley",
        "source_type": "youtube",
        "content_text": "Never gonna give you up never gonna let you down.",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_ingest_api_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(tmp_path / "brain.sqlite3"))
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    init_vault(vault_path=tmp_path)
    from fastapi.testclient import TestClient
    from src.warden.app import app
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/brain/ingest", json={
        "url": "https://example.com",
        "title": "Test",
        "source_type": "webpage",
        "content_text": "No secrets here.",
    })
    assert "access_token" not in resp.text
    assert "client_secret" not in resp.text
    assert "refresh_token" not in resp.text
