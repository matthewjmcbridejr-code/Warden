"""Tests for local Markdown vault management."""
import pytest
from pathlib import Path
from src.warden.brain.vault import (
    init_vault, scan_sources, write_note, _validate_note_path, VAULT_FOLDERS,
)


def test_init_vault_creates_folders(tmp_path):
    result = init_vault(vault_path=tmp_path)
    assert result["initialized"] is True
    assert result["vault_path"] == str(tmp_path)
    for folder in VAULT_FOLDERS:
        assert (tmp_path / folder).exists()


def test_init_vault_idempotent(tmp_path):
    init_vault(vault_path=tmp_path)
    result2 = init_vault(vault_path=tmp_path)
    assert result2["initialized"] is True
    assert not result2["created"]  # nothing created second time


def test_init_vault_writes_readme(tmp_path):
    init_vault(vault_path=tmp_path)
    readme = tmp_path / "00-inbox" / "README.md"
    assert readme.exists()
    assert "Warden Brain Vault" in readme.read_text()


def test_scan_sources_empty(tmp_path):
    init_vault(vault_path=tmp_path)
    sources = scan_sources(vault_path=tmp_path)
    # README.md is a source
    assert any(s.path == "00-inbox/README.md" for s in sources)


def test_scan_sources_finds_markdown(tmp_path):
    init_vault(vault_path=tmp_path)
    (tmp_path / "00-inbox" / "test-note.md").write_text("# Hello\nSome content.")
    sources = scan_sources(vault_path=tmp_path)
    paths = [s.path for s in sources]
    assert "00-inbox/test-note.md" in paths


def test_scan_sources_skips_non_markdown(tmp_path):
    init_vault(vault_path=tmp_path)
    (tmp_path / "00-inbox" / "script.py").write_text("print('hello')")
    (tmp_path / "00-inbox" / "note.md").write_text("# Note")
    sources = scan_sources(vault_path=tmp_path)
    paths = [s.path for s in sources]
    assert "00-inbox/script.py" not in paths


def test_scan_sources_skips_git_dir(tmp_path):
    init_vault(vault_path=tmp_path)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "secret.md").write_text("# Secret")
    sources = scan_sources(vault_path=tmp_path)
    paths = [s.path for s in sources]
    assert not any(".git" in p for p in paths)


def test_write_note_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WARDEN_BRAIN_WRITE_FOLDER", "00-inbox")
    init_vault(vault_path=tmp_path)
    result = write_note("Test Title", "Test body text", vault_path=tmp_path)
    assert result["ok"] is True
    assert Path(result["abs_path"]).exists()
    content = Path(result["abs_path"]).read_text()
    assert "Test Title" in content
    assert "Test body text" in content


def test_write_note_never_overwrites(tmp_path):
    init_vault(vault_path=tmp_path)
    (tmp_path / "00-inbox" / "existing.md").write_text("existing")
    with pytest.raises(FileExistsError):
        write_note("Existing", "body", filename="existing.md", vault_path=tmp_path)


def test_write_note_rejects_path_traversal(tmp_path):
    init_vault(vault_path=tmp_path)
    with pytest.raises(ValueError):
        write_note("Bad", "body", filename="../../etc/passwd", vault_path=tmp_path)


def test_write_note_rejects_absolute_path(tmp_path):
    init_vault(vault_path=tmp_path)
    with pytest.raises(ValueError):
        write_note("Bad", "body", filename="/etc/passwd", vault_path=tmp_path)


def test_write_note_redacts_secrets(tmp_path):
    init_vault(vault_path=tmp_path)
    result = write_note(
        "Oops", "secret=mysecretvalue123 token=abc123",
        vault_path=tmp_path
    )
    content = Path(result["abs_path"]).read_text()
    assert "mysecretvalue123" not in content
    assert "[REDACTED]" in content


def test_validate_note_path_adds_inbox():
    path = _validate_note_path("my-note.md", "00-inbox")
    assert path.startswith("00-inbox/")


def test_validate_note_path_adds_md_extension():
    path = _validate_note_path("my-note", "00-inbox")
    assert path.endswith(".md")
