"""Tests for project-scoped NotebookLM mirror engine, API, and MCP tools."""
import pytest
from pathlib import Path
from src.warden.brain.vault import init_vault, write_note, scan_sources
from src.warden.brain.index import reindex_sources
from src.warden.brain import notebooklm_mirror
from src.warden.workbench import WorkbenchStore, WorkbenchMemoryCreateRequest


def _setup_project_data(tmp_path, project_id="demo-proj"):
    vp = tmp_path / "vault"
    init_vault(vault_path=vp)
    
    # Project-specific note
    write_note(
        "Demo Architecture",
        "Architecture details for demo project. api_key=SECRET_TOKEN_123",
        tags=[project_id, "architecture"],
        filename=f"10-projects/{project_id}/arch.md",
        vault_path=vp,
    )
    # General note (not in project)
    write_note(
        "General Note",
        "Unrelated note content.",
        tags=["general"],
        filename="00-inbox/general.md",
        vault_path=vp,
    )
    # Private note (must be excluded)
    write_note(
        "Private Financials",
        "Private info for demo project.",
        tags=[project_id, "private"],
        filename=f"10-projects/{project_id}/private.md",
        vault_path=vp,
    )

    sources = scan_sources(vault_path=vp)
    idx = tmp_path / "brain.sqlite3"
    reindex_sources(sources, index_path=idx)

    # Workbench memory for project
    wb_root = tmp_path / "workbench"
    store = WorkbenchStore(root=wb_root)
    store.create_memory(WorkbenchMemoryCreateRequest(
        memory_id="m-demo-decision-001",
        scope=project_id,
        summary="Decided to use FastAPI for backend",
        source="captain",
        tags=[project_id, "decision"],
        kind="decision",
        project_id=project_id,
    ))

    return vp, idx, wb_root


def test_notebooklm_mirror_dry_run(tmp_path):
    vp, idx, wb_root = _setup_project_data(tmp_path, "demo-proj")
    result = notebooklm_mirror.mirror_project_to_notebooklm(
        project_id="demo-proj",
        dry_run=True,
        vault_path=vp,
        index_path=idx,
        workbench_root=wb_root,
    )
    assert result["dry_run"] is True
    assert result["synced"] == 0
    assert len(result["would_sync"]) >= 1


def test_notebooklm_mirror_sync(tmp_path):
    vp, idx, wb_root = _setup_project_data(tmp_path, "demo-proj")
    result = notebooklm_mirror.mirror_project_to_notebooklm(
        project_id="demo-proj",
        dry_run=False,
        vault_path=vp,
        index_path=idx,
        workbench_root=wb_root,
    )
    assert result["synced"] >= 1
    assert result["errors"] == 0
    export_dir = Path(result["export_dir"])
    assert export_dir.exists()
    
    index_file = export_dir / "demo-proj_00_index.md"
    assert index_file.exists()
    index_text = index_file.read_text(encoding="utf-8")
    assert "demo-proj" in index_text


def test_notebooklm_mirror_skips_unchanged(tmp_path):
    vp, idx, wb_root = _setup_project_data(tmp_path, "demo-proj")
    res1 = notebooklm_mirror.mirror_project_to_notebooklm(
        project_id="demo-proj",
        dry_run=False,
        vault_path=vp,
        index_path=idx,
        workbench_root=wb_root,
    )
    assert res1["synced"] >= 1

    res2 = notebooklm_mirror.mirror_project_to_notebooklm(
        project_id="demo-proj",
        dry_run=False,
        vault_path=vp,
        index_path=idx,
        workbench_root=wb_root,
    )
    assert res2["skipped"] >= 1
    assert res2["synced"] == 0


def test_notebooklm_mirror_redacts_secrets_and_excludes_private(tmp_path):
    vp, idx, wb_root = _setup_project_data(tmp_path, "demo-proj")
    res = notebooklm_mirror.mirror_project_to_notebooklm(
        project_id="demo-proj",
        dry_run=False,
        vault_path=vp,
        index_path=idx,
        workbench_root=wb_root,
    )
    export_dir = Path(res["export_dir"])

    # Check generated files
    files = list(export_dir.glob("*.md"))
    content_combined = "\n".join(f.read_text(encoding="utf-8") for f in files)
    
    # Redacted secrets check
    assert "SECRET_TOKEN_123" not in content_combined
    assert "[REDACTED]" in content_combined or "api_key" not in content_combined

    # Excluded private note check
    assert "Private info for demo project" not in content_combined


def test_notebooklm_mirror_status(tmp_path):
    vp, idx, wb_root = _setup_project_data(tmp_path, "demo-proj")
    notebooklm_mirror.mirror_project_to_notebooklm(
        project_id="demo-proj",
        dry_run=False,
        vault_path=vp,
        index_path=idx,
        workbench_root=wb_root,
    )
    status = notebooklm_mirror.notebooklm_mirror_status(project_id="demo-proj", index_path=idx)
    assert status["project_id"] == "demo-proj"
    assert "records" in status
    assert len(status["records"]) >= 1
    assert status["counts"].get("synced", 0) >= 1


def test_notebooklm_mirror_mcp_tool(tmp_path, monkeypatch):
    from src.warden.brain_mcp_server import brain_notebooklm_mirror, brain_notebooklm_mirror_status
    import json

    vp, idx, wb_root = _setup_project_data(tmp_path, "demo-mcp")
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(vp))
    monkeypatch.setenv("WARDEN_BRAIN_INDEX_PATH", str(idx))

    res_str = brain_notebooklm_mirror(project_id="demo-mcp", dry_run=False)
    assert "synced" in res_str
    
    status_str = brain_notebooklm_mirror_status(project_id="demo-mcp")
    assert "demo-mcp" in status_str
