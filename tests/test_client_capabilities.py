import json

from src.warden import brain_mcp_server as server


def _catalog_fixture(verify_live_mail=False):
    return {
        "services": [
            {
                "service_id": "warden",
                "kind": "native",
                "operational": True,
                "tool_names": [
                    "warden_bootstrap",
                    "warden_context_pack",
                    "warden_recall",
                    "warden_board",
                    "warden_artifact_store",
                    "warden_artifact_get",
                    "warden_artifact_list",
                    "warden_captain_plan",
                    "warden_run_get",
                    "brain_search",
                ],
            },
            {
                "service_id": "slack",
                "kind": "warden_connector",
                "operational": True,
                "tool_names": ["warden_slack_search"],
            },
            {
                "service_id": "upstream:mctable",
                "kind": "mcp_upstream",
                "operational": True,
                "tool_names": ["mctable_list_shared_agent_skills"],
            },
            {
                "service_id": "upstream:context7",
                "kind": "mcp_upstream",
                "operational": True,
                "tool_names": ["context7_query_docs"],
            },
            {
                "service_id": "mail",
                "kind": "warden_connector",
                "operational": False,
                "tool_names": ["warden_mail_search"],
            },
        ]
    }


def test_capability_catalog_is_client_neutral(monkeypatch):
    monkeypatch.setattr(server, "_service_catalog_data", _catalog_fixture)
    monkeypatch.setattr(server, "compute_tool_catalog_revision", lambda: {"revision_hash": "cat_rev_test"})

    payload = json.loads(server._ok("test", server._capability_catalog_data()))
    capabilities = {row["capability_id"]: row for row in payload["data"]["capabilities"]}

    assert capabilities["shared_context"]["ready"] is True
    assert "warden_context_pack" in capabilities["shared_context"]["tools"]
    assert capabilities["research_and_code"]["ready"] is True
    assert capabilities["shared_skills"]["ready"] is True
    assert capabilities["communication"]["ready"] is True
    assert payload["data"]["policy"]["credentials"] == "remain server-side"


def test_artifact_tools_return_immutable_reference_and_content(monkeypatch):
    monkeypatch.setattr(server, "_remote_bootstrap_error", lambda _tool: None)

    stored = json.loads(server.warden_artifact_store("hello Warden", type="report"))
    assert stored["ok"] is True
    artifact_id = stored["data"]["artifact_id"]
    assert stored["data"]["uri"] == f"warden://artifacts/{artifact_id}"
    assert stored["data"]["immutable"] is True

    fetched = json.loads(server.warden_artifact_get(artifact_id, include_content=True))
    assert fetched["ok"] is True
    assert fetched["data"]["content"] == "hello Warden"

    listed = json.loads(server.warden_artifact_list(limit=10))
    assert any(row["artifact_id"] == artifact_id for row in listed["data"]["artifacts"])


def test_skill_catalog_exposes_bounded_execution_envelopes(monkeypatch):
    monkeypatch.setattr(server, "_remote_bootstrap_error", lambda _tool: None)
    payload = json.loads(server.warden_skill_catalog())
    skills = {row["skill_id"]: row for row in payload["data"]["skills"]}

    assert "role:explorer" in skills
    assert skills["role:explorer"]["execution"]["write_allowed"] is False
    assert skills["role:builder"]["execution"]["dispatch_allowed"] is True
    assert "external side effects" in payload["data"]["execution_policy"]
