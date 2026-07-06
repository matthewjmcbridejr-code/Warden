"""Tests for the Brain dropzone: sort/index files dropped by the user.

See src/warden/brain/dropzone.py and docs/personal_ai_os_plan.md.
"""
from __future__ import annotations

from pathlib import Path

from src.warden.brain import dropzone, mirror
from src.warden.brain.vault import init_vault, scan_sources


def _make_dropzone(tmp_path: Path) -> Path:
    dz = tmp_path / "drop"
    dz.mkdir()
    return dz


def test_sort_drop_folder_indexes_and_moves_file(tmp_path):
    dz = _make_dropzone(tmp_path)
    vault_path = tmp_path / "vault"
    init_vault(vault_path)

    (dz / "warden_research_notes.md").write_text(
        "# Warden Research\n\nSome ideas about the Warden Brain second-brain pattern.",
        encoding="utf-8",
    )

    result = dropzone.sort_drop_folder(dropzone_path=dz, vault_path=vault_path)

    assert result["ok"] is True
    assert len(result["processed"]) == 1
    entry = result["processed"][0]
    assert entry["project"] == "warden"
    assert entry["private"] is False

    # Original file moved into sorted/<project>/, not left in the dropzone root.
    assert not (dz / "warden_research_notes.md").exists()
    assert (dz / "sorted" / "warden" / "warden_research_notes.md").exists()

    # A vault note was written and is discoverable via scan_sources.
    sources = scan_sources(vault_path)
    assert any("warden research" in s.title.lower() for s in sources)


def test_sort_drop_folder_marks_financial_file_private(tmp_path):
    dz = _make_dropzone(tmp_path)
    vault_path = tmp_path / "vault"
    init_vault(vault_path)

    (dz / "Statement - June 2026.md").write_text("Account summary.", encoding="utf-8")

    result = dropzone.sort_drop_folder(dropzone_path=dz, vault_path=vault_path)

    entry = result["processed"][0]
    assert entry["private"] is True

    sources = scan_sources(vault_path)
    note = next(s for s in sources if "statement" in s.title.lower())
    assert "private" in note.tags

    # Privacy tag must be honored by the mirror engine even if Google mirror
    # is otherwise enabled — private/local_only notes never sync out.
    mirror_result = mirror.mirror_sources(vault_path=vault_path, dry_run=True)
    assert not any(s["path"] == note.path for s in mirror_result.get("would_sync", []))


def test_sort_drop_folder_never_reads_or_moves_secret_suspected_files(tmp_path):
    dz = _make_dropzone(tmp_path)
    vault_path = tmp_path / "vault"
    init_vault(vault_path)

    secret_file = dz / "client_secret_abc123.json"
    secret_file.write_text('{"web": {"client_secret": "do-not-read-me"}}', encoding="utf-8")

    result = dropzone.sort_drop_folder(dropzone_path=dz, vault_path=vault_path)

    assert result["processed"] == []
    assert result["skipped"] == [{"file": "client_secret_abc123.json", "reason": "secret-suspected"}]
    # File is left exactly where it was — never moved, never indexed.
    assert secret_file.exists()
    assert not any("client_secret" in s.path or "client_secret" in s.title.lower() for s in scan_sources(vault_path))


def test_sort_drop_folder_dry_run_makes_no_changes(tmp_path):
    dz = _make_dropzone(tmp_path)
    vault_path = tmp_path / "vault"
    init_vault(vault_path)

    (dz / "idea.md").write_text("An idea.", encoding="utf-8")

    result = dropzone.sort_drop_folder(dropzone_path=dz, vault_path=vault_path, dry_run=True)

    assert result["dry_run"] is True
    assert len(result["processed"]) == 1
    assert (dz / "idea.md").exists()  # not moved
    assert not any("idea" in s.title.lower() for s in scan_sources(vault_path))  # no note written


def test_sort_drop_folder_does_not_reprocess_sorted_files(tmp_path):
    dz = _make_dropzone(tmp_path)
    vault_path = tmp_path / "vault"
    init_vault(vault_path)

    (dz / "idea.md").write_text("An idea.", encoding="utf-8")
    dropzone.sort_drop_folder(dropzone_path=dz, vault_path=vault_path)

    result = dropzone.sort_drop_folder(dropzone_path=dz, vault_path=vault_path)
    assert result["processed"] == []
    assert result["skipped"] == []
