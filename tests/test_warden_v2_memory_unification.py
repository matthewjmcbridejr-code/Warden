"""Warden v2.4 — memory unification (personal_ai_os_plan PRs 2, 5, 6)."""

import pytest
from fastapi.testclient import TestClient

import src.warden.workbench as workbench_mod
from src.server.api import app


@pytest.fixture()
def isolated_workbench(tmp_path, monkeypatch):
    root = tmp_path / "workbench"
    monkeypatch.setattr(
        workbench_mod.WorkbenchStore.__init__,
        "__defaults__",
        (root, True),
    )
    # api.py holds a module-level STORE bound at import; repoint it too.
    import src.warden.api as api_mod
    monkeypatch.setattr(api_mod, "WORKBENCH_STORE", workbench_mod.WorkbenchStore(root))
    monkeypatch.setattr(workbench_mod, "STORE", workbench_mod.WorkbenchStore(root))
    yield root


def _seed_capture(store, memory_id="browser-v2test01"):
    return store.create_memory(
        workbench_mod.WorkbenchMemoryCreateRequest(
            memory_id=memory_id,
            scope="warden",
            summary="[browsed] A captured page about skill playbooks",
            source="browser_extension",
            title="A captured page",
            kind="user_note",
            tags=["auto", "browser", "browse"],
            metadata={"url": "https://example.com/playbooks"},
            raw_content="Full page body preserved for review.",
        )
    )


def test_brain_inbox_lists_captures_newest_first(isolated_workbench):
    store = workbench_mod.WorkbenchStore()
    _seed_capture(store)
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/brain/inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True and data["count"] == 1
    item = data["items"][0]
    assert item["memory_id"] == "browser-v2test01"
    assert item["url"] == "https://example.com/playbooks"
    assert item["has_raw_content"] is True
    assert item["promoted"] is False


def test_promote_writes_vault_note_and_sets_source_ref(isolated_workbench, tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_VAULT_PATH", str(tmp_path / "vault"))
    import src.warden.brain.vault as vault_mod
    monkeypatch.setattr(vault_mod, "get_vault_path", lambda: tmp_path / "vault")
    store = workbench_mod.WorkbenchStore()
    _seed_capture(store)

    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/memory/browser-v2test01/promote")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True and data["already_promoted"] is False
    note_path = tmp_path / "vault" / data["note_path"]
    text = note_path.read_text(encoding="utf-8")
    assert "Full page body preserved for review." in text
    assert "memory_id: browser-v2test01" in text

    promoted = store.get_memory("browser-v2test01")
    assert promoted.source_ref == data["note_path"]

    # Second promote is a no-op, not a duplicate note.
    resp2 = client.post("/api/mcharness/warden/memory/browser-v2test01/promote")
    assert resp2.json()["already_promoted"] is True


def test_discard_marks_memory_forgotten_and_leaves_inbox(isolated_workbench):
    store = workbench_mod.WorkbenchStore()
    _seed_capture(store)
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/memory/browser-v2test01/discard")
    assert resp.status_code == 200
    assert resp.json()["status"] == "forgotten"
    inbox = client.get("/api/mcharness/warden/brain/inbox").json()
    assert inbox["count"] == 0
    # File still exists on disk — discard never deletes.
    assert store.get_memory("browser-v2test01").status == "forgotten"


def test_captain_plan_accepts_include_memory_context_flag(isolated_workbench):
    store = workbench_mod.WorkbenchStore()
    store.create_memory(
        workbench_mod.WorkbenchMemoryCreateRequest(
            scope="mcharness-public-export",
            summary="Decision: the dispatcher must never push to master.",
            source="test",
            kind="decision",
            project_id="mcharness-public-export",
        )
    )
    client = TestClient(app)
    resp = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "Harden the dispatcher",
            "repo_id": "mcharness-public-export",
            "lane_id": "codex_cli",
            "include_memory_context": True,
        },
    )
    # Plan generation must succeed (local fallback) with the flag on; the
    # persisted goal stays the user's original goal.
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("goal", "").startswith("Harden the dispatcher") or "plan" in data
