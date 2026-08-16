"""Cold-start and caller-attribution guarantees for Warden's MCP contract."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import src.marius.search_provider as search_provider
import src.warden.brain_mcp_server as server


def _authenticated_hyperagent():
    return SimpleNamespace(client_id="648b242babcdef", subject="operator", token="test-access-token")


def test_bootstrap_schema_allows_a_cold_call_without_task():
    tool = server.mcp._tool_manager._tools["warden_bootstrap"]
    assert "task" not in tool.parameters.get("required", [])


def test_authenticated_caller_identity_uses_oauth_client(monkeypatch):
    monkeypatch.setattr(server, "get_access_token", _authenticated_hyperagent)
    monkeypatch.setattr(
        server,
        "get_client_summary",
        lambda client_id: {"client_id": client_id, "client_name": "Hyperagent"},
    )

    identity = server._current_caller_identity()

    assert identity["agent_id"] == "hyperagent:648b242b"
    assert identity["client_name"] == "Hyperagent"
    assert identity["client_id_prefix"] == "648b242b"
    assert identity["session_id"].endswith(":648b242b")


def test_remote_services_are_locked_until_caller_bootstraps(monkeypatch):
    monkeypatch.setattr(server, "get_access_token", _authenticated_hyperagent)
    monkeypatch.setattr(
        server,
        "get_client_summary",
        lambda client_id: {"client_id": client_id, "client_name": "Hyperagent"},
    )
    server._BOOTSTRAPPED_CALLERS.clear()

    assert "warden_bootstrap" in server._remote_bootstrap_error("github_search_code")
    server._mark_caller_bootstrapped()
    assert server._remote_bootstrap_error("github_search_code") is None


def test_same_access_token_stays_bootstrapped_across_stateless_transport_sessions(monkeypatch):
    monkeypatch.setattr(server, "get_access_token", _authenticated_hyperagent)
    monkeypatch.setattr(
        server,
        "get_client_summary",
        lambda client_id: {"client_id": client_id, "client_name": "Hyperagent"},
    )
    current = {"session": object()}
    monkeypatch.setattr(
        server.mcp,
        "get_context",
        lambda: SimpleNamespace(request_context=SimpleNamespace(session=current["session"])),
    )
    server._BOOTSTRAPPED_CALLERS.clear()

    server._mark_caller_bootstrapped()
    assert server._remote_bootstrap_error("github_search_code") is None

    current["session"] = object()
    assert server._remote_bootstrap_error("github_search_code") is None


def test_new_access_token_must_bootstrap_even_for_same_oauth_client(monkeypatch):
    current_token = {"value": "first-access-token"}

    def authenticated_client():
        return SimpleNamespace(
            client_id="648b242babcdef",
            subject="operator",
            token=current_token["value"],
        )

    monkeypatch.setattr(server, "get_access_token", authenticated_client)
    monkeypatch.setattr(
        server,
        "get_client_summary",
        lambda client_id: {"client_id": client_id, "client_name": "Hyperagent"},
    )
    server._BOOTSTRAPPED_CALLERS.clear()

    server._mark_caller_bootstrapped()
    assert server._remote_bootstrap_error("github_search_code") is None

    current_token["value"] = "second-access-token"
    assert "warden_bootstrap" in server._remote_bootstrap_error("github_search_code")


def test_remote_native_write_is_blocked_before_bootstrap(monkeypatch):
    monkeypatch.setattr(server, "get_access_token", _authenticated_hyperagent)
    monkeypatch.setattr(
        server,
        "get_client_summary",
        lambda client_id: {"client_id": client_id, "client_name": "Hyperagent"},
    )
    server._BOOTSTRAPPED_CALLERS.clear()

    payload = json.loads(server.warden_remember(kind="decision", text="must not be written"))

    assert payload["ok"] is False
    assert "warden_bootstrap" in payload["error"]


def test_cold_bootstrap_returns_guardrails_claims_and_freshness(monkeypatch):
    old = datetime(2026, 6, 27, tzinfo=timezone.utc)
    fresh = datetime(2026, 8, 15, tzinfo=timezone.utc)
    decision = SimpleNamespace(
        memory_id="m-native-mcp",
        title="Use native MCP",
        summary="Do not use Drive as the primary synchronization path.",
        kind="decision",
        project_id="Warden",
        scope="Warden",
        tags=["no-repeat"],
        updated_at=fresh,
        status="active",
    )

    class FakeStore:
        def list_memories(self):
            return [decision]

        def search_memories(self, query, *, scope=None, limit=10):
            return []

        def build_memory_context_pack(self, **kwargs):
            return {"context": "current Warden context", "memory_ids": [decision.memory_id]}

    class FakeSearchProvider:
        def search(self, *args, **kwargs):
            return []

    monkeypatch.setattr(server, "seed_if_missing", lambda: None)
    monkeypatch.setattr(server, "load_profile", lambda: {
        "name": "Matt",
        "active_projects": ["Warden"],
        "current_priorities": [],
        "preferences": {},
        "server_context": {},
        "last_updated": old.date().isoformat(),
    })
    monkeypatch.setattr(server, "get_workstream", lambda **kwargs: [])
    monkeypatch.setattr(server, "_store", FakeStore)
    monkeypatch.setattr(server, "_semantic_recall", lambda *args, **kwargs: [])
    monkeypatch.setattr(search_provider, "LocalJsonlSearchProvider", FakeSearchProvider)
    monkeypatch.setattr(server, "get_access_token", _authenticated_hyperagent)
    monkeypatch.setattr(
        server,
        "get_client_summary",
        lambda client_id: {"client_id": client_id, "client_name": "Hyperagent"},
    )
    monkeypatch.setattr(server, "warden_board", lambda: json.dumps({
        "ok": True,
        "data": {
            "open_tasks": [{"task_id": "existing-task", "project": "Warden"}],
            "active_claims": [{"agent": "codex", "task": "existing-task"}],
            "recent_handoffs": [],
        },
    }))
    monkeypatch.setattr(server, "_service_catalog_data", lambda verify_live_mail: {
        "summary": {"service_count": 3, "operational_service_count": 3},
        "services": [{"service_id": "upstream:context7", "operational": True}],
    })
    server._BOOTSTRAPPED_CALLERS.clear()

    payload = json.loads(server.warden_bootstrap())

    assert payload["ok"] is True
    data = payload["data"]
    assert data["task"] == ""
    assert data["caller"]["agent_id"] == "hyperagent:648b242b"
    assert data["relevant_memories"][0]["memory_id"] == "m-native-mcp"
    assert data["coordination"]["open_tasks"][0]["task_id"] == "existing-task"
    assert data["freshness"]["warning"] is not None
    assert data["available_services"]["services"][0]["service_id"] == "upstream:context7"
    assert server._remote_bootstrap_error("github_search_code") is None


def test_service_catalog_combines_native_mail_and_upstream_readiness(monkeypatch):
    monkeypatch.setattr(server, "get_access_token", lambda: None)
    monkeypatch.setattr(server, "_mail_accounts_status_data", lambda verify_live: {
        "configured": True,
        "operational": True,
        "count": 2,
        "configured_count": 2,
        "operational_count": 1,
        "verified_live": verify_live,
        "accounts": [
            {
                "account_id": "gmail-1",
                "provider": "gmail",
                "display_email": "one@example.com",
                "status": "connected",
                "capabilities": ["mail.read", "mail.search"],
                "health": {"state": "needs_reauth", "operational": False},
            },
            {
                "account_id": "icloud-1",
                "provider": "icloud",
                "display_email": "two@example.com",
                "status": "connected",
                "capabilities": ["mail.read", "mail.search"],
                "health": {"state": "operational", "operational": True},
            },
        ],
    })
    monkeypatch.setattr(server.mcp_hub, "hub_status", lambda: SimpleNamespace(
        hub_tool_names=["github_search_code", "context7_query_docs"],
        hub_tool_count=2,
        upstreams=[
            {
                "name": "mctable", "reachable": True, "tool_count": 1,
                "discovered_tool_count": 1, "blocked_by_policy": 4,
                "tool_names": ["github_search_code"], "error": None,
            },
            {
                "name": "context7", "reachable": True, "tool_count": 1,
                "discovered_tool_count": 1, "blocked_by_policy": 0,
                "tool_names": ["context7_query_docs"], "error": None,
            },
        ],
    ))

    payload = json.loads(server.warden_service_catalog())

    assert payload["ok"] is True
    data = payload["data"]
    assert data["summary"]["mail_configured_count"] == 2
    assert data["summary"]["mail_operational_count"] == 1
    mail = next(row for row in data["services"] if row["service_id"] == "mail")
    assert mail["accounts"][0]["capabilities"] == ["mail.read", "mail.search"]
    assert mail["accounts"][1]["health"]["operational"] is True
    github = next(row for row in data["services"] if row["service_id"] == "upstream:mctable")
    assert github["tool_names"] == ["github_search_code"]
    assert github["blocked_by_policy"] == 4
    assert "token" not in json.dumps(data).lower()
    assert "password" not in json.dumps(data).lower()


def test_board_reconciles_duplicate_and_closed_task_claims(tmp_path, monkeypatch):
    board = tmp_path / "board"
    (board / "tasks" / "claimed").mkdir(parents=True)
    (board / "claims").mkdir(parents=True)
    open_task = {
        "task_id": "open-task", "title": "Open", "project": "Warden", "status": "claimed",
    }
    (board / "tasks" / "claimed" / "open-task.json").write_text(json.dumps(open_task))
    active_claim = {
        "ts": "2026-08-15T05:00:00+00:00", "agent": "codex", "action": "CLAIM",
        "task": "open-task",
    }
    closed_claim = {
        "ts": "2026-06-27T03:00:00+00:00", "agent": "claude", "action": "CLAIM",
        "task": "already-closed",
    }
    (board / "claims" / "active.jsonl").write_text(
        "\n".join([json.dumps(active_claim), json.dumps(active_claim), json.dumps(closed_claim)]) + "\n"
    )
    (board / "claims" / "codex_open-task.json").write_text(json.dumps(active_claim))
    monkeypatch.setattr(server, "BOARD_ROOT", board)

    payload = json.loads(server.warden_board())

    assert payload["data"]["active_claims"] == [active_claim]
    assert payload["data"]["stale_claims"] == [
        {**closed_claim, "reconciled_status": "stale_task_not_open"},
    ]


def test_tool_catalog_revision_stability(tmp_path, monkeypatch):
    data_dir = tmp_path / "warden_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WARDEN_DATA_ROOT", str(data_dir))

    res1_str = server.warden_bootstrap(task="Test 1", project="warden", detail="minimal")
    res1 = json.loads(res1_str)
    rev1 = res1["data"]["tool_catalog_revision"]

    # 1. Adding a memory must NOT change revision_hash
    server.warden_remember(kind="decision", text="Added a random decision memory", project="warden")
    res2_str = server.warden_bootstrap(task="Test 2", project="warden", detail="minimal")
    res2 = json.loads(res2_str)
    rev2 = res2["data"]["tool_catalog_revision"]

    assert rev1["revision_hash"] == rev2["revision_hash"], "Adding a memory must not alter tool catalog revision!"
    assert rev1["native_tool_count"] == rev2["native_tool_count"]
    assert rev1["total_tool_count"] == rev2["total_tool_count"]

    # 2. Changing health/time timestamps must NOT change revision_hash
    monkeypatch.setenv("DUMMY_TIMESTAMP", "2026-08-16T12:34:56Z")
    res3_str = server.warden_bootstrap(task="Test 3", project="warden", detail="minimal")
    res3 = json.loads(res3_str)
    rev3 = res3["data"]["tool_catalog_revision"]

    assert rev1["revision_hash"] == rev3["revision_hash"], "Timestamp shifts must not alter tool catalog revision!"

    # 3. Adding a new tool MUST change revision_hash
    @server.mcp.tool()
    def temporary_dummy_tool_for_test() -> str:
        return "dummy"

    try:
        res4_str = server.warden_bootstrap(task="Test 4", project="warden", detail="minimal")
        res4 = json.loads(res4_str)
        rev4 = res4["data"]["tool_catalog_revision"]

        assert rev4["revision_hash"] != rev1["revision_hash"], "Adding a tool MUST change tool catalog revision!"
        assert rev4["native_tool_count"] == rev1["native_tool_count"] + 1
    finally:
        server.mcp._tool_manager._tools.pop("temporary_dummy_tool_for_test", None)

