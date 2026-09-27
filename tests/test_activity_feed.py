"""Activity feed: agent, landing place, and no copied secrets or note bodies."""
from __future__ import annotations

import asyncio
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.warden.activity_feed import (
    build_activity_feed,
    classify_tool,
    record_mcp_call,
    write_mcp_runtime_status,
)
from src.warden.app import app
from src.warden.brain.vault import init_vault, write_note
from src.warden.workbench import (
    WorkbenchArtifactCreateRequest,
    WorkbenchMemoryRememberRequest,
    WorkbenchStore,
)


def test_classify_tool_matches_real_write_tools():
    assert classify_tool("brain_write_note") == "brain"
    assert classify_tool("warden_remember") == "memory"
    assert classify_tool("warden_post_task") == "board"
    assert classify_tool("warden_artifact_store") == "artifact"
    assert classify_tool("warden_recall") == "mcp"
    assert classify_tool("mctable_get_health") == "mcp"


def test_journal_redacts_secrets_and_omits_arguments(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_ACTIVITY_DIR", str(tmp_path))
    record_mcp_call(
        agent="cursor:test",
        tool="warden_remember",
        ok=False,
        ref="m-1",
        error="api_key=supersecretvalue",
    )
    raw = (tmp_path / "mcp-calls.jsonl").read_text(encoding="utf-8")
    assert "supersecretvalue" not in raw
    assert "REDACTED" in raw
    row = json.loads(raw)
    assert row["tool"] == "warden_remember"
    assert row["destination"] == "mcp"
    assert row["landed"] == "memory"
    assert "arguments" not in row


def test_feed_shows_agent_and_landing_without_note_body(tmp_path, monkeypatch):
    activity = tmp_path / "activity"
    vault = tmp_path / "vault"
    board = tmp_path / "board"
    monkeypatch.setenv("WARDEN_ACTIVITY_DIR", str(activity))
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(vault))
    monkeypatch.setenv("WARDEN_BOARD_ROOT", str(board))
    init_vault(vault_path=vault)
    secret_body = "BODY-SHOULD-NOT-LEAK-9f3a api_key=notforfeed"
    write_note(
        "Vault decision",
        secret_body,
        tags=["warden"],
        vault_path=vault,
        extra_frontmatter={"agent": "cursor:test"},
    )
    day = board / "activity" / "2026-09-27"
    day.mkdir(parents=True)
    (day / "cursor.jsonl").write_text(
        json.dumps({
            "ts": "2026-09-27T07:00:00+00:00",
            "agent": "cursor:test",
            "action": "POST_TASK",
            "task": "task-1",
            "note": "Write the dashboard",
        }) + "\n",
        encoding="utf-8",
    )
    store = WorkbenchStore(tmp_path / "wb")
    store.remember_memory(WorkbenchMemoryRememberRequest(
        content="Remembered a local decision",
        title="Local decision",
        source="warden-brain-mcp",
        kind="decision",
        project_id="Warden",
        agent_id="cursor:test",
    ))
    store.create_artifact(WorkbenchArtifactCreateRequest(
        artifact_id="art_test_one",
        kind="report",
        title="Dispatch report",
        path="reports/dispatch.md",
    ))
    record_mcp_call(agent="cursor:test", tool="warden_recall", ok=True, ref="")
    write_mcp_runtime_status({
        "native_tool_count": 3,
        "hub_tool_count": 1,
        "upstreams": [{"name": "context7", "reachable": True, "tool_count": 1, "error": None}],
    })

    feed = build_activity_feed(memory_store=store)
    blob = json.dumps(feed)
    assert "BODY-SHOULD-NOT-LEAK-9f3a" not in blob
    assert "notforfeed" not in blob
    by_dest = {}
    for event in feed["events"]:
        by_dest.setdefault(event["destination"], []).append(event)

    brain = by_dest["brain"][0]
    assert brain["agent"] == "cursor:test"
    assert brain["title"] == "Vault decision"
    assert brain["ref"].endswith(".md")

    memory = by_dest["memory"][0]
    assert memory["agent"] == "cursor:test"
    assert memory["project"] == "Warden"
    assert memory["action"] == "decision"

    board_row = by_dest["board"][0]
    assert board_row["agent"] == "cursor:test"
    assert board_row["ref"] == "task-1"

    mcp_rows = [row for row in feed["events"] if row["action"] == "call"]
    assert any(row["tool"] == "warden_recall" and row["agent"] == "cursor:test" for row in mcp_rows)
    assert by_dest["artifact"][0]["agent"] is None
    assert feed["mcp_runtime"]["native_tool_count"] == 3

    only_mcp = build_activity_feed(memory_store=store, destination="mcp")
    assert only_mcp["events"]
    assert all(row["action"] == "call" for row in only_mcp["events"])


def test_mcp_tracer_records_tool_not_arguments(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_ACTIVITY_DIR", str(tmp_path))
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("WARDEN_AGENT_ID", "cursor-test")
    from src.warden.brain_mcp_server import mcp

    asyncio.run(mcp._tool_manager.call_tool(
        "brain_status",
        {"api_key": "SUPERSECRETVALUE"},
    ))
    raw = (tmp_path / "mcp-calls.jsonl").read_text(encoding="utf-8")
    assert "SUPERSECRETVALUE" not in raw
    assert "brain_status" in raw
    assert "cursor-test" in raw


def test_cloud_backend_reads_sql_records_not_a_lab_log(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_ACTIVITY_DIR", str(tmp_path / "activity"))
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path / "empty-vault"))
    monkeypatch.setenv("WARDEN_BOARD_ROOT", str(tmp_path / "board"))
    store_rows = {
        "mcp_call": [],
        "mission": [{
            "mission_id": "mission-1",
            "kind": "repo_status",
            "status": "completed",
            "worker_id": "cloud-worker",
            "updated_at": "2026-09-27T08:00:00+00:00",
            "body": {"title": "Cloud mission"},
        }],
        "artifact": [{
            "artifact_id": "art_cloud",
            "created_by": "cloud-worker",
            "created_at": "2026-09-27T08:01:00+00:00",
            "uri": "warden://artifacts/art_cloud",
        }],
        "mcp_runtime": [],
    }

    class FakePlane:
        def upsert_record(self, record_type, record_id, payload, source_updated_at=None):
            store_rows.setdefault(record_type, []).insert(0, payload)

        def list_records(self, record_type, limit=100):
            return list(store_rows.get(record_type, []))[:limit]

    monkeypatch.setattr("src.warden.cloud_control_plane.cloud_control_enabled", lambda: True)
    monkeypatch.setattr("src.warden.cloud_control_plane.CloudControlPlane", lambda *args, **kwargs: FakePlane())
    monkeypatch.setattr("src.warden.cloud_brain.is_cloud_primary", lambda: True)

    record_mcp_call(agent="cursor:test", tool="warden_remember", ok=True, ref="m-cloud")
    assert not (tmp_path / "activity" / "mcp-calls.jsonl").exists()

    feed = build_activity_feed(memory_store=_EmptyStore(), include_memory=True)
    calls = [row for row in feed["events"] if row["action"] == "call"]
    assert calls and calls[0]["tool"] == "warden_remember"
    assert calls[0]["landed"] == "memory"
    assert any(row["ref"] == "mission-1" and row["agent"] == "cloud-worker" for row in feed["events"])
    assert any(row["agent"] == "cloud-worker" and row["destination"] == "artifact" for row in feed["events"])
    assert feed["placement"]["control_plane"] == "cloud"
    assert "6969" in feed["placement"]["retired_local_ui"]
    blob = json.dumps(feed)
    assert "mclab" in blob


class _EmptyStore:
    def list_memories(self):
        return []

    def list_artifacts(self):
        return []


def test_activity_api_and_page(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_ACTIVITY_DIR", str(tmp_path / "activity"))
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("WARDEN_BOARD_ROOT", str(tmp_path / "board"))
    monkeypatch.setenv("WARDEN_LOCAL_DESK", "1")
    init_vault(vault_path=tmp_path / "vault")
    store = WorkbenchStore(tmp_path / "wb")
    store.remember_memory(WorkbenchMemoryRememberRequest(
        content="API memory row",
        title="API memory",
        source="test",
        agent_id="agy",
        kind="fact",
        project_id="Warden",
    ))
    monkeypatch.setattr("src.warden.workbench.WorkbenchStore", lambda *args, **kwargs: store)

    client = TestClient(app)
    page = client.get("/web/warden/app.html")
    assert page.status_code == 200
    assert 'data-testid="nav-activity"' in page.text
    assert 'id="warden-section-activity"' in page.text

    resp = client.get("/api/mcharness/warden/activity")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert any(row["title"] == "API memory" and row["agent"] == "agy" for row in body["events"])
    labels = {row["id"] for row in body["coverage"]}
    assert {"memory", "brain", "mcp", "board", "artifact"} <= labels

    def deny(request=None):
        raise HTTPException(status_code=403, detail="Warden Memory is available only on the private runner service.")

    monkeypatch.setattr("src.warden.api._require_private_memory_access", deny)
    blocked = client.get("/api/mcharness/warden/activity")
    assert blocked.status_code == 200
    blocked_body = blocked.json()
    assert all(row["destination"] != "memory" for row in blocked_body["events"])
    memory_cov = next(row for row in blocked_body["coverage"] if row["id"] == "memory")
    assert memory_cov["included"] is False
