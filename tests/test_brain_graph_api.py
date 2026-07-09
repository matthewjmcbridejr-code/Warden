"""Tests for GET /api/brain/graph — the Brain Graph view's data source.

Read-only: proves the endpoint builds nodes/edges from real indexed vault
sources and agent memories, with the edge rules described in
src/warden/brain/graph.py (same project, shared tags, markdown links).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.warden.brain.graph import build_graph
from src.warden.brain.vault import init_vault


def _note(vp: Path, rel_path: str, *, title: str, body: str, tags: list[str] | None = None) -> None:
    """Write a note straight to an arbitrary vault-relative path.

    write_note() always forces new notes into WARDEN_BRAIN_WRITE_FOLDER
    (00-inbox) regardless of the filename passed in — correct behavior for
    real capture, but it means these tests need direct control over which
    vault folder (10-projects, 20-people, ...) a note lands in to exercise
    the graph's folder-based typing.
    """
    p = vp / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    tag_str = ", ".join(tags or [])
    p.write_text(f"---\ntitle: {title}\ntags: {tag_str}\n---\n\n# {title}\n\n{body}\n", encoding="utf-8")


def test_build_graph_empty_vault_returns_empty_lists(tmp_path, monkeypatch):
    # Memories aren't vault-scoped, so isolate this assertion from whatever
    # proofs/decisions/etc. already exist in the real WorkbenchStore.
    from src.warden.workbench import STORE as WORKBENCH_STORE
    monkeypatch.setattr(WORKBENCH_STORE, "list_memories", lambda: [])

    vp = tmp_path / "vault"
    init_vault(vp)
    data = build_graph(vault_path=vp)
    assert data["nodes"] == []
    assert data["edges"] == []


def test_build_graph_nodes_typed_by_folder(tmp_path):
    vp = tmp_path / "vault"
    init_vault(vp)
    _note(vp, "10-projects/warden-note.md", title="Warden project note", body="Agent ops cockpit.", tags=["warden"])
    _note(vp, "20-people/matt.md", title="Matt Profile", body="Who Matt is.", tags=["person"])
    _note(vp, "00-inbox/raw.md", title="Raw capture", body="unsorted", tags=["dropzone"])

    data = build_graph(vault_path=vp)
    by_label = {n["label"]: n for n in data["nodes"]}

    assert by_label["Warden project note"]["type"] == "project"
    assert by_label["Warden project note"]["project"] == "warden"
    assert by_label["Matt Profile"]["type"] == "person"
    assert by_label["Raw capture"]["type"] == "inbox"
    assert by_label["Raw capture"]["status"] == "raw"


def test_build_graph_shared_project_creates_edge(tmp_path):
    vp = tmp_path / "vault"
    init_vault(vp)
    _note(vp, "10-projects/a.md", title="Warden A", body="a", tags=["warden"])
    _note(vp, "10-projects/b.md", title="Warden B", body="b", tags=["warden"])

    data = build_graph(vault_path=vp)
    node_ids = {n["label"]: n["id"] for n in data["nodes"]}
    a_id, b_id = node_ids["Warden A"], node_ids["Warden B"]
    matching = [e for e in data["edges"] if {e["source"], e["target"]} == {a_id, b_id}]
    assert any(e["type"] == "project" for e in matching)


def test_build_graph_shared_tag_creates_edge(tmp_path):
    vp = tmp_path / "vault"
    init_vault(vp)
    _note(vp, "50-research/a.md", title="Note A", body="a", tags=["hydraulics"])
    _note(vp, "50-research/b.md", title="Note B", body="b", tags=["hydraulics"])

    data = build_graph(vault_path=vp)
    node_ids = {n["label"]: n["id"] for n in data["nodes"]}
    a_id, b_id = node_ids["Note A"], node_ids["Note B"]
    matching = [e for e in data["edges"] if {e["source"], e["target"]} == {a_id, b_id}]
    assert any(e["type"] == "tag" for e in matching)


def test_build_graph_wikilink_creates_edge(tmp_path):
    vp = tmp_path / "vault"
    init_vault(vp)
    _note(vp, "50-research/target-note.md", title="Target Note", body="the target")
    _note(vp, "50-research/source-note.md", title="Source Note", body="see [[Target Note]] for more")

    data = build_graph(vault_path=vp)
    node_ids = {n["label"]: n["id"] for n in data["nodes"]}
    src_id, tgt_id = node_ids["Source Note"], node_ids["Target Note"]
    matching = [e for e in data["edges"] if {e["source"], e["target"]} == {src_id, tgt_id}]
    assert any(e["type"] == "link" for e in matching)


def test_build_graph_node_size_grows_with_degree(tmp_path):
    vp = tmp_path / "vault"
    init_vault(vp)
    for i in range(5):
        _note(vp, f"10-projects/w{i}.md", title=f"Warden {i}", body="x", tags=["warden"])
    _note(vp, "50-research/lonely.md", title="Lonely", body="x")

    data = build_graph(vault_path=vp)
    by_label = {n["label"]: n for n in data["nodes"]}
    assert by_label["Warden 0"]["size"] > by_label["Lonely"]["size"]


def test_graph_endpoint_returns_real_indexed_sources(tmp_path, monkeypatch):
    vp = tmp_path / "vault"
    init_vault(vp)
    _note(vp, "10-projects/endpoint-test.md", title="Endpoint Test Note", body="content for the endpoint test", tags=["warden"])
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(vp))

    from src.warden.app import app
    client = TestClient(app)
    resp = client.get("/api/brain/graph")

    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data and "edges" in data
    labels = [n["label"] for n in data["nodes"]]
    assert "Endpoint Test Note" in labels
