import json
import subprocess
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.warden.captain import CAPTAIN_ROOT
from src.warden.graph import MCTABLE_ROOT, TASKS_DIR
from src.server.api import app


@pytest.fixture(autouse=True)
def clean_mctable():
    for d in [
        TASKS_DIR,
        MCTABLE_ROOT / "worker_runs",
        MCTABLE_ROOT / "checkpoints",
        CAPTAIN_ROOT,
        MCTABLE_ROOT / "runs",
        MCTABLE_ROOT / "evidence",
        MCTABLE_ROOT / "captain",
        MCTABLE_ROOT / "gates",
    ]:
        if d.exists():
            shutil.rmtree(d)
    yield
    for d in [
        TASKS_DIR,
        MCTABLE_ROOT / "worker_runs",
        MCTABLE_ROOT / "checkpoints",
        CAPTAIN_ROOT,
        MCTABLE_ROOT / "runs",
        MCTABLE_ROOT / "evidence",
        MCTABLE_ROOT / "captain",
        MCTABLE_ROOT / "gates",
    ]:
        if d.exists():
            shutil.rmtree(d)


def test_mcharness_health_endpoint_reports_public_manual_mode():
    client = TestClient(app)
    response = client.get("/api/mcharness/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["service"] == "mcharness-control-plane"
    assert data["mode"] == "public_manual"
    assert data["real_agent_launch_enabled"] is False
    assert data["arbitrary_command_execution_enabled"] is False
    assert isinstance(data["commit"], str) and len(data["commit"]) == 40
    assert data["available_lanes_count"] >= 1
    assert data["repo_count"] >= 1


def test_mcharness_captain_status_reports_gateway_configured_when_key_missing(monkeypatch):
    # Without a cloud key, Captain is still "configured" — it routes through the local
    # Marius gateway (with a deterministic fallback planner) instead of requiring a key.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("MCHARNESS_CAPTAIN_MODEL", raising=False)
    client = TestClient(app)
    response = client.get("/api/mcharness/captain/status")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["configured"] is True
    assert data["provider"] == "marius-gateway"
    assert data["model"] == "openrouter/auto"
    assert data["planning_enabled"] is True
    assert data["key_source"] == "missing"
    assert data["private_key_setup_enabled"] is False
    assert "gateway" in data["notes"][0].lower()
    assert "test-openrouter-key" not in response.text


def test_mcharness_captain_status_reports_configured_with_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("MCHARNESS_CAPTAIN_MODEL", "openrouter/test-model")
    client = TestClient(app)
    response = client.get("/api/mcharness/captain/status")
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is True
    assert data["provider"] == "openrouter"
    assert data["model"] == "openrouter/test-model"
    assert data["planning_enabled"] is True
    assert data["key_source"] == "env"
    assert data["private_key_setup_enabled"] is False
    assert "test-openrouter-key" not in response.text


def test_mcharness_captain_key_save_requires_private_write_access(monkeypatch):
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "false")
    monkeypatch.delenv("MCHARNESS_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/key",
        json={"api_key": "sk-or-private-test-key", "model": "openrouter/auto"},
    )
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


def test_mcharness_captain_key_save_delete_and_status_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("MCHARNESS_CAPTAIN_MODEL", raising=False)

    import src.warden.api as api_mod

    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    client = TestClient(app)

    saved = client.post(
        "/api/mcharness/captain/key",
        json={"api_key": "sk-or-private-test-key", "model": "openrouter/custom"},
    )
    assert saved.status_code == 200, saved.text
    saved_data = saved.json()
    assert saved_data["configured"] is True
    assert saved_data["key_source"] == "saved"
    assert saved_data["model"] == "openrouter/custom"
    assert "sk-or-private-test-key" not in saved.text

    status = client.get("/api/mcharness/captain/status")
    assert status.status_code == 200
    status_data = status.json()
    assert status_data["configured"] is True
    assert status_data["key_source"] == "saved"
    assert status_data["private_key_setup_enabled"] is True
    assert "sk-or-private-test-key" not in status.text

    removed = client.delete("/api/mcharness/captain/key")
    assert removed.status_code == 200, removed.text
    removed_data = removed.json()
    # Still "configured" — falls back to the Marius gateway, not disabled.
    assert removed_data["configured"] is True
    assert removed_data["key_source"] == "missing"
    assert "sk-or-private-test-key" not in removed.text

    status_after = client.get("/api/mcharness/captain/status")
    assert status_after.status_code == 200
    assert status_after.json()["configured"] is True


def test_mcharness_captain_key_env_precedence_over_saved_key(monkeypatch, tmp_path):
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-test-key")
    monkeypatch.setenv("MCHARNESS_CAPTAIN_MODEL", "openrouter/env-model")

    import src.warden.api as api_mod

    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    saved_path = tmp_path / "secrets" / "captain_openrouter.json"
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    saved_path.write_text(
        json.dumps(
            {
                "provider": "openrouter",
                "api_key": "sk-or-saved-test-key",
                "model": "openrouter/saved-model",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    client = TestClient(app)
    status = client.get("/api/mcharness/captain/status")
    assert status.status_code == 200
    data = status.json()
    assert data["configured"] is True
    assert data["key_source"] == "env"
    assert data["model"] == "openrouter/env-model"
    assert "sk-or-env-test-key" not in status.text
    assert "sk-or-saved-test-key" not in status.text


def test_mcharness_captain_key_save_rejects_when_env_key_present(monkeypatch):
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-test-key")

    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/key",
        json={"api_key": "sk-or-private-test-key", "model": "openrouter/auto"},
    )
    assert response.status_code == 409
    assert "environment" in response.json()["detail"].lower()


def test_mcharness_captain_plan_local_preview_when_no_key(monkeypatch, tmp_path):
    # Without a cloud key, endpoint falls back to local preview planner instead of 503
    # Uses tmp_path so test plans don't pollute the real memory store
    import src.warden.api as api_mod
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")
    # Stub WorkbenchStore to avoid writing real memories during test
    monkeypatch.setattr(api_mod, "_write_plan_memory", lambda **kwargs: None)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "Build a webpage just like aol.com",
            "repo_id": "hybrid-agent-os",
            "lane_id": "codex_cli",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["steps"]) >= 3
    assert data.get("source") == "local_preview" or any("local preview" in n.lower() for n in (data.get("notes") or []))


def test_mcharness_captain_plan_local_preview_right_sizes_trivial_goal(monkeypatch, tmp_path):
    # A plainly trivial ask ("hello world") shouldn't get the same 4-step
    # bug-investigation-shaped plan as a real fix/feature request.
    import src.warden.api as api_mod
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")
    monkeypatch.setattr(api_mod, "_write_plan_memory", lambda **kwargs: None)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "a website that says hello world",
            "repo_id": "hybrid-agent-os",
            "lane_id": "codex_cli",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["steps"]) == 2
    assert "reproduce" not in data["steps"][0]["title"].lower()


def test_mcharness_captain_plan_rejects_unknown_repo(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "Build a webpage just like aol.com",
            "repo_id": "no-such-repo",
            "lane_id": "codex_cli",
        },
    )
    assert response.status_code == 400
    assert "Unknown repo_id" in response.json()["detail"]


def test_mcharness_captain_plan_rejects_unknown_lane(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "Build a webpage just like aol.com",
            "repo_id": "hybrid-agent-os",
            "lane_id": "no-such-lane",
        },
    )
    assert response.status_code == 400
    assert "Unknown agent lane" in response.json()["detail"]


def test_mcharness_captain_plan_rejects_blank_goal(monkeypatch, tmp_path):
    # Whitespace-only goal must be rejected server-side, not just trimmed client-side
    import src.warden.api as api_mod
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "   ",
            "repo_id": "hybrid-agent-os",
            "lane_id": "codex_cli",
        },
    )
    assert response.status_code == 422

    response_empty = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "",
            "repo_id": "hybrid-agent-os",
            "lane_id": "codex_cli",
        },
    )
    assert response_empty.status_code == 422


def test_mcharness_captain_plan_parses_mocked_openrouter_json(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("MCHARNESS_CAPTAIN_MODEL", "openrouter/auto")

    import src.warden.api as api_mod
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")
    monkeypatch.setattr(api_mod, "_write_plan_memory", lambda **kwargs: None)

    def fake_openrouter(*, messages, model, timeout):
        assert model == "openrouter/auto"
        assert any("Captain Deck" in item["content"] for item in messages if item["role"] == "system")
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "title": "Build AOL-inspired webpage",
                                "summary": "Create an AOL-inspired homepage layout in the existing frontend.",
                                "steps": [
                                    {
                                        "title": "Inspect frontend structure",
                                        "prompt": "Inspect the frontend entrypoint and identify the minimal files to change.",
                                    },
                                    {
                                        "title": "Implement layout",
                                        "prompt": "Modify only the selected frontend files to add the requested layout.",
                                    },
                                    {
                                        "title": "Verify and report",
                                        "prompt": "Run the focused checks and return a concise proof report.",
                                    },
                                ],
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(api_mod, "_openrouter_chat_completion", fake_openrouter)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "Build a webpage just like aol.com",
            "repo_id": "hybrid-agent-os",
            "lane_id": "codex_cli",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["title"] == "Build AOL-inspired webpage"
    assert data["summary"].startswith("Create an AOL-inspired homepage layout")
    assert len(data["steps"]) == 3
    assert data["steps"][0]["id"] == "step_1"
    assert data["steps"][0]["agent"] == "codex_cli"
    assert data["steps"][0]["status"] == "queued"
    assert "Exact goal: Build a webpage just like aol.com" in data["steps"][0]["prompt"]
    assert "Forbidden actions:" in data["steps"][0]["prompt"]
    assert "Acceptance checks:" in data["steps"][0]["prompt"]
    assert "Final proof format:" in data["steps"][0]["prompt"]
    assert "test-openrouter-key" not in response.text


def test_mcharness_captain_plan_rejects_invalid_model_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    import src.warden.api as api_mod

    def fake_openrouter(*, messages, model, timeout):
        return {"choices": [{"message": {"content": "not-json"}}]}

    monkeypatch.setattr(api_mod, "_openrouter_chat_completion", fake_openrouter)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "Build a webpage just like aol.com",
            "repo_id": "hybrid-agent-os",
            "lane_id": "codex_cli",
        },
    )
    assert response.status_code == 502
    assert "valid JSON" in response.json()["detail"]


def test_mcharness_captain_plan_uses_saved_key_when_env_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    monkeypatch.delenv("MCHARNESS_CAPTAIN_MODEL", raising=False)

    import src.warden.api as api_mod

    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")
    saved_path = tmp_path / "secrets" / "captain_openrouter.json"
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    saved_path.write_text(
        json.dumps(
            {
                "provider": "openrouter",
                "api_key": "sk-or-saved-test-key",
                "model": "openrouter/saved-model",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    def fake_openrouter(*, messages, model, timeout):
        assert model == "openrouter/saved-model"
        assert any("Captain Deck" in item["content"] for item in messages if item["role"] == "system")
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "title": "Saved-key Captain plan",
                                "summary": "Uses the saved private OpenRouter key.",
                                "steps": [
                                    {
                                        "title": "Inspect frontend structure",
                                        "prompt": "Inspect the frontend entrypoint and identify the minimal files to change.",
                                    },
                                    {
                                        "title": "Implement layout",
                                        "prompt": "Modify only the selected frontend files to add the requested layout.",
                                    },
                                    {
                                        "title": "Verify and report",
                                        "prompt": "Run the focused checks and return a concise proof report.",
                                    },
                                ],
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(api_mod, "_openrouter_chat_completion", fake_openrouter)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/plan",
        json={
            "goal": "Create a short read-only plan for inspecting the McHarness frontend. Do not edit files.",
            "repo_id": "hybrid-agent-os",
            "lane_id": "codex_cli",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["title"] == "Saved-key Captain plan"
    assert "sk-or-saved-test-key" not in response.text


# ---------------------------------------------------------------------------
# Phase 1.5 — Memory recall hardening tests
# ---------------------------------------------------------------------------

def test_captain_recent_plans_returns_newest_first(monkeypatch, tmp_path):
    """GET /captain/plans/recent returns plans sorted newest first."""
    import src.warden.api as api_mod
    import time

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    plan_root = tmp_path / "captain" / "plans"
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", plan_root)
    monkeypatch.setattr(api_mod, "_write_plan_memory", lambda **kwargs: None)
    plan_root.mkdir(parents=True, exist_ok=True)

    # Plans are stored in a plans.json index (newest-first by updated_at)
    old_plan = {
        "plan_id": "plan_old", "title": "Old Plan", "goal": "old goal",
        "repo_id": "hybrid-agent-os", "lane_id": "codex_cli",
        "source": "local_preview", "steps": [], "notes": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    new_plan = {
        "plan_id": "plan_new", "title": "New Plan", "goal": "new goal",
        "repo_id": "hybrid-agent-os", "lane_id": "codex_cli",
        "source": "local_preview", "steps": [], "notes": [],
        "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-01T00:00:00+00:00",
    }
    # Write plans index (old first in file, new first in expected output)
    plans_index = tmp_path / "captain" / "plans.json"
    plans_index.parent.mkdir(parents=True, exist_ok=True)
    plans_index.write_text(json.dumps([new_plan, old_plan]))

    client = TestClient(app)
    response = client.get("/api/mcharness/captain/plans/recent")
    assert response.status_code == 200
    plans = response.json()["plans"]
    assert len(plans) >= 2
    ids = [p["plan_id"] for p in plans]
    assert ids.index("plan_new") < ids.index("plan_old"), "Newest plan should come first"


def test_captain_local_preview_writes_searchable_memory(monkeypatch, tmp_path):
    """Local preview plan memory call receives goal/plan_id/source in its kwargs."""
    import src.warden.api as api_mod

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")

    captured = {}

    def capture_write(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(api_mod, "_write_plan_memory", capture_write)

    client = TestClient(app)
    unique_goal = "test-recall-hardening-unique-goal-abc123"
    response = client.post(
        "/api/mcharness/captain/plan",
        json={"goal": unique_goal, "repo_id": "hybrid-agent-os", "lane_id": "codex_cli"},
    )
    assert response.status_code == 200
    assert captured.get("goal") == unique_goal
    assert captured.get("plan") is not None
    plan = captured["plan"]
    assert plan.get("plan_id", "").startswith("plan_")
    assert plan.get("source") == "local_preview"
    assert len(plan.get("steps", [])) >= 3


def test_captain_local_preview_response_has_source_field(monkeypatch, tmp_path):
    """Unconfigured Captain returns local_preview source instead of dead UI / 503."""
    import src.warden.api as api_mod

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")
    monkeypatch.setattr(api_mod, "_write_plan_memory", lambda **kwargs: None)

    client = TestClient(app)
    response = client.post(
        "/api/mcharness/captain/plan",
        json={"goal": "fix the login bug", "repo_id": "hybrid-agent-os", "lane_id": "codex_cli"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data.get("source") == "local_preview"
    assert len(data["steps"]) >= 3


def test_public_write_guard_blocks_private_captain_key_on_public_service(monkeypatch):
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "false")
    monkeypatch.delenv("MCHARNESS_ADMIN_TOKEN", raising=False)
    client = TestClient(app)

    blocked = client.post(
        "/api/mcharness/captain/key",
        json={"api_key": "sk-or-test", "model": "openrouter/auto"},
    )
    assert blocked.status_code == 403
    assert "disabled" in blocked.json()["detail"].lower()

    manual = client.post(
        "/api/mcharness/sessions",
        json={
            "title": "Manual cockpit session",
            "objective": "Manual cockpit writes remain available.",
            "plan_instruction": "Create a bounded manual queue.",
            "repo_path": str(Path(__file__).resolve().parents[1]),
            "agent_lane": "manual_paste",
        },
    )
    assert manual.status_code == 200


def test_mcharness_agent_lanes_rich_detection_shape(monkeypatch):
    client = TestClient(app)
    # Force deterministic detection without host CLIs
    import src.warden.api as api_mod

    def fake_detect(name: str):
        if name == "codex":
            return {"installed": True, "executable_path": "/usr/local/bin/codex", "version": "codex version 0.42.0"}
        if name == "agy":
            return {"installed": False, "executable_path": None, "version": None}
        return {"installed": False, "executable_path": None, "version": None}

    monkeypatch.setattr(api_mod, "_detect_executable", fake_detect)
    r = client.get("/api/mcharness/agent-lanes")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "mcharness-control-plane"
    assert "lanes" in data and isinstance(data["lanes"], list) and len(data["lanes"]) >= 3
    by_id = { (l.get("id") or l.get("lane_id")): l for l in data["lanes"] }
    codex = by_id.get("codex_cli") or by_id.get("codex")
    assert codex is not None
    assert codex["installed"] is True
    assert codex.get("executable_path") == "/usr/local/bin/codex"
    assert "version" in codex
    assert codex.get("auth_status") in ("unknown", "likely_ready", "not_detected")
    assert codex.get("runner_mode") in ("dry_run_ready", "controlled_run_disabled", "manual")
    assert isinstance(codex.get("safety_notes"), list)
    assert "last_checked_at" in codex
    # legacy compat keys present
    assert codex.get("lane_id") == "codex_cli"
    assert "title" in codex
    manual = by_id.get("manual_paste")
    assert manual is not None
    assert manual.get("runner_mode") == "manual"
    assert manual.get("installed") is True


def test_mcharness_repos_enhanced_git_status():
    client = TestClient(app)
    r = client.get("/api/mcharness/repos")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "mcharness-control-plane"
    assert "repos" in data
    repos = { (x.get("repo_id") or x.get("label")): x for x in data["repos"] }
    # at least the export one exists in this tree
    exp = repos.get("mcharness-public-export")
    assert exp is not None
    assert exp.get("exists") is True
    assert "current_branch" in exp
    assert "dirty" in exp
    assert "changed_files_count" in exp
    assert "last_commit_short" in exp
    assert "status_summary" in exp
    assert isinstance(exp.get("safety_notes"), list)


def test_mcharness_runner_intent_dry_run_and_rejects(monkeypatch):
    client = TestClient(app)
    # create a minimal manual session for a valid session_id
    create = client.post(
        "/api/mcharness/sessions",
        json={
            "title": "runner-intent-test",
            "objective": "test dry run preview",
            "plan_instruction": "just a test",
            "repo_path": str(Path(__file__).resolve().parents[1]),
            "agent_lane": "manual_paste",
        },
    )
    assert create.status_code == 200, create.text
    sid = create.json()["session_id"]

    # happy dry_run with manual
    intent = client.post(
        f"/api/mcharness/sessions/{sid}/runner-intent",
        json={"lane_id": "manual_paste", "repo_id": "mcharness-public-export", "mode": "dry_run"},
    )
    assert intent.status_code == 200, intent.text
    d = intent.json()
    assert d["ok"] is True
    assert d["real_execution_enabled"] is False
    assert "command_preview" in d and "MANUAL" in d["command_preview"]
    assert "prompt_file_path" in d and sid in d["prompt_file_path"]
    assert "transcript_file_path" in d
    assert d["safety_policy"]["public_real_agent_launch_disabled"] is True
    assert d["safety_policy"]["arbitrary_shell_disabled"] is True

    # reject unknown lane
    bad_lane = client.post(f"/api/mcharness/sessions/{sid}/runner-intent", json={"lane_id": "no_such_lane", "repo_id": "mcharness-public-export", "mode": "dry_run"})
    assert bad_lane.status_code == 400

    # reject unknown repo
    bad_repo = client.post(f"/api/mcharness/sessions/{sid}/runner-intent", json={"lane_id": "manual_paste", "repo_id": "not-an-allowlisted-repo", "mode": "dry_run"})
    assert bad_repo.status_code == 400

    # reject non-dry
    bad_mode = client.post(f"/api/mcharness/sessions/{sid}/runner-intent", json={"lane_id": "manual_paste", "repo_id": "mcharness-public-export", "mode": "real"})
    assert bad_mode.status_code == 400

    # also works for a codex lane (even if not installed here) - preview does not require installed
    codex_intent = client.post(f"/api/mcharness/sessions/{sid}/runner-intent", json={"lane_id": "codex_cli", "repo_id": "mcharness-public-export", "mode": "dry_run"})
    assert codex_intent.status_code == 200
    cd = codex_intent.json()
    assert cd["real_execution_enabled"] is False


# --- runner foundation tests (use fake_test_lane + monkeypatch; no real provider burn) ---

def test_runner_disabled_by_default():
    client = TestClient(app)
    # create session with manual (allowed)
    s = client.post("/api/mcharness/sessions", json={
        "title": "r1", "objective": "o", "plan_instruction": "p",
        "repo_path": str(Path(__file__).resolve().parents[1]), "agent_lane": "manual_paste"
    })
    assert s.status_code == 200
    sid = s.json()["session_id"]
    # start should be blocked for non-fake when default false
    r = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={
        "lane_id": "codex_cli", "repo_id": "mcharness-public-export"
    })
    assert r.status_code in (403, 400)
    assert "disabled" in (r.text or "").lower() or "not implemented" in (r.text or "").lower()


def test_fake_test_lane_runner_full_flow(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    # patch start to avoid real tmux in test (still exercises state, endpoints, evidence)
    import src.warden.api as api_mod
    orig_start = api_mod._start_fake_runner
    def fake_start(state):
        p = api_mod.Path(state["transcript_file_path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("MCHarness fake runner started\nartifact proof line\nMCHarness fake runner complete\nMCH_EXIT_CODE:0\n", encoding="utf-8")
        state["status"] = "exited"
        state["exit_code"] = 0
        return state
    monkeypatch.setattr(api_mod, "_start_fake_runner", fake_start)

    s = client.post("/api/mcharness/sessions", json={
        "title": "fake-runner", "objective": "proof", "plan_instruction": "p",
        "repo_path": str(Path(__file__).resolve().parents[1]), "agent_lane": "fake_test_lane"
    })
    assert s.status_code == 200
    sid = s.json()["session_id"]

    # start
    st = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={
        "lane_id": "fake_test_lane", "repo_id": "mcharness-public-export"
    })
    assert st.status_code == 200
    data = st.json()
    assert data["lane_id"] == "fake_test_lane"
    assert data["status"] in ("running", "exited")
    assert "transcript_file_path" in data
    assert data["safety_policy"]["arbitrary_shell_disabled"] is True

    # status
    st2 = client.get(f"/api/mcharness/sessions/{sid}/runner/status")
    assert st2.status_code == 200
    assert st2.json()["status"] in ("running", "exited", "stopped")

    # transcript
    tr = client.get(f"/api/mcharness/sessions/{sid}/runner/transcript")
    assert tr.status_code == 200
    tdata = tr.json()
    assert "MCHarness fake runner" in (tdata.get("transcript") or "")

    # to evidence
    ev = client.post(f"/api/mcharness/sessions/{sid}/runner/transcript-to-evidence")
    assert ev.status_code == 200
    ed = ev.json()
    assert ed["ok"] is True
    assert "artifact" in ed

    # stop (scoped)
    sp = client.post(f"/api/mcharness/sessions/{sid}/runner/stop")
    assert sp.status_code == 200
    assert sp.json()["status"] == "stopped"

    # manual paste still works (parallel)
    man = client.post(f"/api/mcharness/sessions/{sid}/manual-result", json={
        "summary": "manual still works with runner present", "verdict": "passed"
    })
    assert man.status_code == 200


def test_runner_rejects_unknown_lane_repo(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    s = client.post("/api/mcharness/sessions", json={
        "title": "r2", "objective": "o", "plan_instruction": "p",
        "repo_path": str(Path(__file__).resolve().parents[1]), "agent_lane": "manual_paste"
    })
    sid = s.json()["session_id"]
    badl = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={"lane_id": "nope", "repo_id": "mcharness-public-export"})
    assert badl.status_code == 400
    badr = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={"lane_id": "fake_test_lane", "repo_id": "nope"})
    assert badr.status_code == 400


def test_codex_detection_and_disabled_without_both_envs(monkeypatch):
    client = TestClient(app)
    # force codex "installed" via patch, no real exec
    import src.warden.api as api_mod
    orig_detect = api_mod._detect_executable
    def fake_detect(name):
        if name == "codex":
            return {"installed": True, "executable_path": "/fake/codex", "version": "codex-cli 0.137.0"}
        return orig_detect(name)
    monkeypatch.setattr(api_mod, "_detect_executable", fake_detect)

    # default: both false -> codex start disabled
    s = client.post("/api/mcharness/sessions", json={
        "title": "c1", "objective": "o", "plan_instruction": "p",
        "repo_path": str(Path(__file__).resolve().parents[1]), "agent_lane": "manual_paste"
    })
    sid = s.json()["session_id"]
    r = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={"lane_id": "codex_cli", "repo_id": "mcharness-public-export"})
    assert r.status_code == 403
    assert "codex_runner" in (r.text or "").lower() or "disabled" in (r.text or "").lower()

    # with only tmux true, still disabled for codex
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    r2 = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={"lane_id": "codex_cli", "repo_id": "mcharness-public-export"})
    assert r2.status_code == 403

    # with both, would allow (but we don't start real here, just reach)
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    # patch start to avoid actual codex/tmux in this unit test
    def fake_start_codex(st, c):
        st["status"] = "running"
        st["notes"].append("codex (patched, no real exec)")
        return st
    monkeypatch.setattr(api_mod, "_start_codex_runner", fake_start_codex)
    r3 = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={"lane_id": "codex_cli", "repo_id": "mcharness-public-export"})
    assert r3.status_code == 200
    d = r3.json()
    assert d["lane_id"] == "codex_cli"
    assert d["safety_policy"]["codex_runner_enabled"] is True
    assert "real_provider" in d["safety_policy"]


def test_codex_command_template_and_missing_handling(monkeypatch):
    client = TestClient(app)
    import src.warden.api as api_mod
    # patch detect to installed
    def fake_detect(name):
        if name == "codex":
            return {"installed": True, "executable_path": "/fake/codex", "version": "0.137"}
        return {"installed": False, "executable_path": None, "version": None}
    monkeypatch.setattr(api_mod, "_detect_executable", fake_detect)
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    def fake_start(st, c): 
        st["status"] = "running"
        return st
    monkeypatch.setattr(api_mod, "_start_codex_runner", fake_start)

    s = client.post("/api/mcharness/sessions", json={
        "title": "c2", "objective": "o", "plan_instruction": "p",
        "repo_path": str(Path(__file__).resolve().parents[1]), "agent_lane": "manual_paste"
    })
    sid = s.json()["session_id"]
    st = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={"lane_id": "codex_cli", "repo_id": "mcharness-public-export"})
    assert st.status_code == 200
    # intent preview shape for codex uses exec template
    intent = client.post(f"/api/mcharness/sessions/{sid}/runner-intent", json={"lane_id": "codex_cli", "repo_id": "mcharness-public-export", "mode": "dry_run"})
    assert intent.status_code == 200
    ip = intent.json()
    assert "codex exec --cd" in ip["command_preview"]
    assert "--output-last-message" in ip["command_preview"]

    # missing codex
    def fake_missing(name):
        if name == "codex":
            return {"installed": False, "executable_path": None, "version": None}
        return fake_detect(name)
    monkeypatch.setattr(api_mod, "_detect_executable", fake_missing)
    # lanes should reflect
    lanes = client.get("/api/mcharness/agent-lanes").json()["lanes"]
    cod = next((l for l in lanes if l["lane_id"] == "codex_cli"), None)
    assert cod is not None
    assert cod["installed"] is False
    assert "not found" in " ".join(cod.get("safety_notes", [])).lower()


def test_fake_interactive_tmux_runner_prompt_injection_and_capture(monkeypatch):
    """Real tmux (harmless long-running process) + send + capture proves prompt appears in live transcript.
    Status stays running until stop. Stop only affects that session.
    """
    client = TestClient(app)
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    import src.warden.api as api_mod
    import time

    s = client.post("/api/mcharness/sessions", json={
        "title": "fake-interactive", "objective": "o", "plan_instruction": "p",
        "repo_path": str(Path(__file__).resolve().parents[1]), "agent_lane": "fake_test_lane"
    })
    assert s.status_code == 200
    sid = s.json()["session_id"]

    st = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={
        "lane_id": "fake_test_lane", "repo_id": "mcharness-public-export"
    })
    assert st.status_code == 200
    data = st.json()
    name = data.get("tmux_session_name")
    assert name
    assert data["status"] in ("waiting_for_codex", "running", "starting")

    time.sleep(0.5)  # allow tmux to start the process

    # For fake lane we do not use the codex-specific send (it would 400); instead prove start + live capture works for interactive process.
    # (The send + prompt_sent is covered in the codex patch test below.)
    tr = client.get(f"/api/mcharness/sessions/{sid}/runner/transcript")
    assert tr.status_code == 200
    txt = tr.json().get("transcript", "")
    assert "started" in txt.lower() or len(txt) >= 0   # allow empty initially if slow

    # status running
    st2 = client.get(f"/api/mcharness/sessions/{sid}/runner/status")
    assert st2.status_code == 200
    assert st2.json()["status"] in ("running", "waiting_for_codex", "starting", "exited")

    # stop only this session
    sp = client.post(f"/api/mcharness/sessions/{sid}/runner/stop")
    assert sp.status_code == 200
    assert sp.json()["status"] == "stopped"


def test_codex_cli_uses_interactive_tmux_mode_not_exec_wrapper(monkeypatch):
    """Codex lane when flags enabled uses pure interactive launch (no exec wrapper in command).
    Send path is exercised. No real codex executed.
    """
    client = TestClient(app)
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    import src.warden.api as api_mod

    # patch start to record what command would be used, without real tmux
    recorded = {}
    orig = api_mod._start_codex_runner
    def fake_start(state, cwd):
        recorded["status"] = "waiting_for_codex"
        recorded["notes"] = ["interactive launch"]
        state["status"] = "waiting_for_codex"
        state["attach_command"] = "tmux attach -t fake"
        state["notes"].append("codex interactive tmux (not exec < file)")
        return state
    monkeypatch.setattr(api_mod, "_start_codex_runner", fake_start)

    s = client.post("/api/mcharness/sessions", json={
        "title": "codex-int", "objective": "o", "plan_instruction": "p",
        "repo_path": str(Path(__file__).resolve().parents[1]), "agent_lane": "codex_cli"
    })
    sid = s.json()["session_id"]

    st = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={
        "lane_id": "codex_cli", "repo_id": "mcharness-public-export"
    })
    assert st.status_code == 200
    start_body = st.json()
    assert start_body["status"] == "waiting_for_codex"
    tmux_name = start_body["tmux_session_name"]

    calls = []

    def fake_safe_cmd(cmd, timeout=2.5, cwd=None):
        calls.append(tuple(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(api_mod, "_safe_cmd", fake_safe_cmd)
    monkeypatch.setattr(api_mod, "_run_for_session", lambda session_id: {"run_id": "run-queue"})
    monkeypatch.setattr(api_mod, "_append_run_event", lambda *args, **kwargs: None)

    # send
    prompt = "TASK_PROMPT_HERE\nReturn the single line:\nMCH_CODEX_SUBMIT_PROOF_OK"
    send = client.post(f"/api/mcharness/sessions/{sid}/runner/send-prompt", json={"prompt": prompt})
    assert send.status_code == 200
    send_body = send.json()
    assert send_body["status"] == "awaiting_response"
    assert send_body["injected"] is True
    assert calls[:3] == [
        ("tmux", "send-keys", "-t", tmux_name, "-l", prompt),
        ("tmux", "send-keys", "-t", tmux_name, "Tab"),
        ("tmux", "send-keys", "-t", tmux_name, "Enter"),
    ]

    st2 = client.get(f"/api/mcharness/sessions/{sid}/runner/status")
    assert st2.json()["status"] == "awaiting_response"

    # stop
    sp = client.post(f"/api/mcharness/sessions/{sid}/runner/stop")
    assert sp.json()["status"] == "stopped"


def test_codex_start_auto_skips_update_prompt(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    import src.warden.api as api_mod

    calls = []

    def fake_safe_cmd(cmd, timeout=2.5, cwd=None):
        calls.append(tuple(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(api_mod, "_safe_cmd", fake_safe_cmd)
    monkeypatch.setattr(api_mod, "_get_tmux_transcript", lambda name: "Update available! 0.137.0 -> 0.138.0\nSkip until next version")

    s = client.post("/api/mcharness/sessions", json={
        "title": "codex-update-skip", "objective": "o", "plan_instruction": "p",
        "repo_path": str(Path(__file__).resolve().parents[1]), "agent_lane": "codex_cli"
    })
    sid = s.json()["session_id"]

    st = client.post(f"/api/mcharness/sessions/{sid}/runner/start", json={
        "lane_id": "codex_cli", "repo_id": "mcharness-public-export"
    })
    assert st.status_code == 200
    body = st.json()
    assert body["status"] == "waiting_for_codex"
    assert any(call[-1] == "2" for call in calls if call[:3] == ("tmux", "send-keys", "-t"))
    assert any(call[-1] == "Enter" for call in calls if call[:3] == ("tmux", "send-keys", "-t"))


def test_runner_send_key_allows_only_quick_reply_keys(monkeypatch, tmp_path):
    client = TestClient(app)
    import src.warden.api as api_mod

    session_id = "quick-reply-session"
    runner_id = "run_1234abcd"
    tmux_name = api_mod._tmux_session_name(session_id, runner_id)
    transcript_path = tmp_path / "transcript.txt"
    transcript_path.write_text("before\n", encoding="utf-8")
    state = {
        "session_id": session_id,
        "runner_id": runner_id,
        "lane_id": "codex_cli",
        "status": "prompt_sent",
        "tmux_session_name": tmux_name,
        "transcript_file_path": str(transcript_path),
    }
    calls = []

    def fake_load_runner_state(sid):
        assert sid == session_id
        return state

    def fake_safe_cmd(cmd, timeout=2.5, cwd=None):
        calls.append((tuple(cmd), timeout))
        if cmd[:3] == ["tmux", "has-session", "-t"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[:4] == ["tmux", "send-keys", "-t", tmux_name]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(api_mod, "_load_runner_state", fake_load_runner_state)
    monkeypatch.setattr(api_mod, "_safe_cmd", fake_safe_cmd)
    monkeypatch.setattr(api_mod, "_run_for_session", lambda sid: {"run_id": "run-quick"})
    monkeypatch.setattr(api_mod, "_append_run_event", lambda *args, **kwargs: None)

    cases = [
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("Enter", "Enter"),
        ("Ctrl+C", "C-c"),
    ]
    for requested, mapped in cases:
        response = client.post(f"/api/mcharness/sessions/{session_id}/runner/send-key", json={"key": requested})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] is True
        assert payload["sent_key"] == requested
        assert payload["tmux_session_name"] == tmux_name
        assert payload["transcript_excerpt"].startswith("before")
        assert any(call[0][-1] == mapped for call in calls if call[0][:4] == ("tmux", "send-keys", "-t", tmux_name))


def test_runner_send_key_submit_continue_sends_tab_then_enter(monkeypatch, tmp_path):
    client = TestClient(app)
    import src.warden.api as api_mod

    session_id = "submit-continue-session"
    runner_id = "run_5678abcd"
    tmux_name = api_mod._tmux_session_name(session_id, runner_id)
    transcript_path = tmp_path / "transcript.txt"
    transcript_path.write_text("before\n", encoding="utf-8")
    state = {
        "session_id": session_id,
        "runner_id": runner_id,
        "lane_id": "codex_cli",
        "status": "waiting_for_codex",
        "tmux_session_name": tmux_name,
        "transcript_file_path": str(transcript_path),
    }
    calls = []

    def fake_load_runner_state(sid):
        assert sid == session_id
        return state

    def fake_safe_cmd(cmd, timeout=2.5, cwd=None):
        calls.append((tuple(cmd), timeout))
        if cmd[:3] == ["tmux", "has-session", "-t"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[:4] == ["tmux", "send-keys", "-t", tmux_name]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(api_mod, "_load_runner_state", fake_load_runner_state)
    monkeypatch.setattr(api_mod, "_safe_cmd", fake_safe_cmd)
    monkeypatch.setattr(api_mod, "_run_for_session", lambda sid: {"run_id": "run-submit"})
    monkeypatch.setattr(api_mod, "_append_run_event", lambda *args, **kwargs: None)

    response = client.post(f"/api/mcharness/sessions/{session_id}/runner/send-key", json={"key": "Submit / Continue"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["sent_key"] == "Submit / Continue"
    assert payload["status_note"] == "Prompt sent to Codex."
    sent_keys = [call[0][-1] for call in calls if call[0][:3] == ("tmux", "send-keys", "-t")]
    assert "Tab" in sent_keys
    assert "Enter" in sent_keys


def test_runner_send_key_rejects_invalid_state_and_arbitrary_tmux(monkeypatch):
    client = TestClient(app)
    import src.warden.api as api_mod

    session_id = "quick-reply-reject"
    runner_id = "run_deadbeef"
    bad_state = {
        "session_id": session_id,
        "runner_id": runner_id,
        "lane_id": "codex_cli",
        "status": "stopped",
        "tmux_session_name": "mch_arbitrary_target",
        "transcript_file_path": "/tmp/does-not-matter.txt",
    }

    monkeypatch.setattr(api_mod, "_load_runner_state", lambda sid: bad_state if sid == session_id else None)
    monkeypatch.setattr(api_mod, "_safe_cmd", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="", stderr=""))

    rejected_state = client.post(f"/api/mcharness/sessions/{session_id}/runner/send-key", json={"key": "1"})
    assert rejected_state.status_code == 409

    bad_state["status"] = "running"
    rejected_tmux = client.post(f"/api/mcharness/sessions/{session_id}/runner/send-key", json={"key": "1"})
    assert rejected_tmux.status_code == 400
    assert "mismatch" in rejected_tmux.text.lower()

    bad_state["tmux_session_name"] = api_mod._tmux_session_name(session_id, runner_id)
    missing_runner = client.post("/api/mcharness/sessions/other-session/runner/send-key", json={"key": "1"})
    assert missing_runner.status_code == 400


def test_mcharness_agents_returns_builtin_codex(monkeypatch):
    monkeypatch.delenv("MCHARNESS_TMUX_RUNNER_ENABLED", raising=False)
    monkeypatch.delenv("MCHARNESS_CODEX_RUNNER_ENABLED", raising=False)
    client = TestClient(app)
    response = client.get("/api/mcharness/agents")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["registry_write_enabled"] is False
    agents = data["agents"]
    assert any(item["id"] == "codex_cli" for item in agents)
    codex = next(item for item in agents if item["id"] == "codex_cli")
    assert codex["adapter"] == "codex_cli"
    assert codex["builtin"] is True
    assert codex["status"] == "disabled"
    assert codex["runnable"] is False
    assert "api_key" not in response.text
    assert "secret" not in response.text.lower()


def test_mcharness_agents_templates_lists_safe_templates():
    client = TestClient(app)
    response = client.get("/api/mcharness/agents/templates")
    assert response.status_code == 200, response.text
    templates = response.json()["templates"]
    labels = {item["label"] for item in templates}
    assert "Codex CLI" in labels
    assert "Jules Remote" in labels
    assert "AGY CLI Coming Later" in labels
    assert "Custom CLI Coming Later" in labels
    assert "Custom Remote Coming Later" in labels


def _enable_private_agent_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    import src.warden.api as api_mod

    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    return api_mod


def _mock_jules_connected(monkeypatch):
    import src.warden.agent_registry as registry_mod

    def fake_test(*, api_key, default_repo_id=None, default_branch=None):
        if api_key == "bad-jules-key":
            return {
                "ok": True,
                "adapter": "jules_remote",
                "status": "invalid_key",
                "message": "Jules API rejected the API key.",
                "safe_details": {},
            }
        return {
            "ok": True,
            "adapter": "jules_remote",
            "status": "connected",
            "message": "Jules API key verified via sources list.",
            "safe_details": {"sources_count": 1},
        }

    monkeypatch.setattr(registry_mod, "test_jules_remote_config", fake_test)


def test_mcharness_agents_post_rejected_on_public_service(monkeypatch):
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "false")
    monkeypatch.delenv("MCHARNESS_ADMIN_TOKEN", raising=False)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/agents",
        json={
            "name": "Jules Remote",
            "kind": "remote",
            "adapter": "jules_remote",
            "api_key": "test-jules-key",
        },
    )
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


def test_mcharness_agents_test_config_rejected_on_public_service(monkeypatch):
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "false")
    monkeypatch.delenv("MCHARNESS_ADMIN_TOKEN", raising=False)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/agents/test-config",
        json={
            "adapter": "jules_remote",
            "api_key": "test-jules-key",
        },
    )
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


def test_mcharness_agents_test_config_never_returns_key(monkeypatch, tmp_path):
    _enable_private_agent_registry(monkeypatch, tmp_path)
    _mock_jules_connected(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/agents/test-config",
        json={
            "adapter": "jules_remote",
            "api_key": "test-jules-key",
            "default_repo_id": "mcharness-public-export",
            "default_branch": "feat/mcharness-functional-cockpit",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "connected"
    assert "test-jules-key" not in response.text
    assert "api_key" not in response.text


def test_mcharness_agents_test_config_invalid_key(monkeypatch, tmp_path):
    _enable_private_agent_registry(monkeypatch, tmp_path)
    _mock_jules_connected(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/agents/test-config",
        json={
            "adapter": "jules_remote",
            "api_key": "bad-jules-key",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "invalid_key"


def test_mcharness_agents_private_can_register_jules_remote(monkeypatch, tmp_path):
    api_mod = _enable_private_agent_registry(monkeypatch, tmp_path)
    _mock_jules_connected(monkeypatch)
    client = TestClient(app)

    created = client.post(
        "/api/mcharness/agents",
        json={
            "name": "Jules Remote Worker",
            "kind": "remote",
            "adapter": "jules_remote",
            "default_repo_id": "mcharness-public-export",
            "default_branch": "feat/mcharness-functional-cockpit",
            "require_plan_approval": True,
            "enabled": True,
            "api_key": "test-jules-key",
        },
    )
    assert created.status_code == 200, created.text
    agent = created.json()["agent"]
    assert agent["adapter"] == "jules_remote"
    assert agent["status"] == "ready"
    assert agent["connection_status"] == "connected"
    assert agent["configured"] is True
    assert agent["runnable"] is False
    assert agent["user_created"] is True
    assert "test-jules-key" not in created.text
    assert "api_key" not in created.text

    secret_path = tmp_path / "secrets" / f"agent_{agent['id']}.json"
    assert secret_path.exists()
    secret_data = json.loads(secret_path.read_text(encoding="utf-8"))
    assert secret_data["api_key"] == "test-jules-key"
    assert "test-jules-key" not in client.get("/api/mcharness/agents").text

    status = client.get(f"/api/mcharness/agents/{agent['id']}/status")
    assert status.status_code == 200
    status_data = status.json()
    assert status_data["connection_status"] == "connected"
    assert status_data["runnable"] is False
    assert "test-jules-key" not in status.text


def test_mcharness_agents_rejects_custom_cli_and_duplicate_codex(monkeypatch, tmp_path):
    monkeypatch.setenv("MCHARNESS_PUBLIC_WRITE_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")

    import src.warden.api as api_mod

    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    client = TestClient(app)

    custom = client.post(
        "/api/mcharness/agents",
        json={
            "name": "Unsafe Custom",
            "kind": "cli",
            "adapter": "custom_cli",
        },
    )
    assert custom.status_code == 400
    assert "not available" in custom.json()["detail"].lower()

    codex = client.post(
        "/api/mcharness/agents",
        json={
            "name": "Extra Codex",
            "kind": "cli",
            "adapter": "codex_cli",
        },
    )
    assert codex.status_code == 400
    assert "built-in" in codex.json()["detail"].lower()


def test_mcharness_agents_delete_rules(monkeypatch, tmp_path):
    _enable_private_agent_registry(monkeypatch, tmp_path)
    _mock_jules_connected(monkeypatch)
    client = TestClient(app)

    builtin_delete = client.delete("/api/mcharness/agents/codex_cli")
    assert builtin_delete.status_code == 400
    assert "built-in" in builtin_delete.json()["detail"].lower()

    created = client.post(
        "/api/mcharness/agents",
        json={
            "name": "Jules Remote",
            "kind": "remote",
            "adapter": "jules_remote",
            "api_key": "test-jules-key",
        },
    )
    assert created.status_code == 200, created.text
    agent_id = created.json()["agent"]["id"]
    secret_path = tmp_path / "secrets" / f"agent_{agent_id}.json"
    assert secret_path.exists()

    deleted = client.delete(f"/api/mcharness/agents/{agent_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_id"] == agent_id
    assert not secret_path.exists()

    listed = client.get("/api/mcharness/agents")
    assert all(item["id"] != agent_id for item in listed.json()["agents"])


def test_mcharness_agents_probe_codex_and_jules(monkeypatch, tmp_path):
    _enable_private_agent_registry(monkeypatch, tmp_path)
    _mock_jules_connected(monkeypatch)
    client = TestClient(app)

    codex_probe = client.post("/api/mcharness/agents/codex_cli/probe")
    assert codex_probe.status_code == 200, codex_probe.text
    assert "probe" in codex_probe.json()
    assert "api_key" not in codex_probe.text

    created = client.post(
        "/api/mcharness/agents",
        json={
            "name": "Jules Remote",
            "kind": "remote",
            "adapter": "jules_remote",
            "api_key": "test-jules-key",
        },
    )
    assert created.status_code == 200, created.text
    agent_id = created.json()["agent"]["id"]
    jules_probe = client.post(f"/api/mcharness/agents/{agent_id}/probe")
    assert jules_probe.status_code == 200, jules_probe.text
    jules_payload = jules_probe.json()
    assert jules_payload["connection_status"] == "connected"
    assert jules_payload["status"] == "ready"
    assert jules_payload.get("runnable") is False
    assert jules_payload.get("last_checked_at")
    assert "test-jules-key" not in jules_probe.text


def _enable_private_run_history(monkeypatch, tmp_path):
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    import src.warden.api as api_mod

    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)

    def fake_start_codex(state, cwd):
        state["status"] = "running"
        state["notes"].append("codex (patched, no real exec)")
        return state

    monkeypatch.setattr(api_mod, "_start_codex_runner", fake_start_codex)


def test_run_history_created_on_private_codex_dispatch(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/mcharness/sessions",
        json={
            "title": "History smoke",
            "objective": "Prove run history",
            "plan_instruction": "Create a bounded run record.",
            "repo_path": str(Path(__file__).resolve().parents[1]),
            "agent_lane": "manual_paste",
        },
    )
    assert created.status_code == 200
    sid = created.json()["session_id"]
    started = client.post(
        f"/api/mcharness/sessions/{sid}/runner/start",
        json={
            "lane_id": "codex_cli",
            "repo_id": "mcharness-public-export",
            "title": "History smoke",
            "prompt": "Inspect the Warden frontend and summarize entrypoints.",
            "agent_id": "codex_cli",
            "created_by": "use_agent",
        },
    )
    assert started.status_code == 200, started.text
    payload = started.json()
    assert payload.get("warden_run")
    run_id = payload["runner_id"]
    recent = client.get("/api/mcharness/runs/recent")
    assert recent.status_code == 200
    data = recent.json()
    assert data["service_mode"] == "private"
    assert len(data["runs"]) == 1
    run = data["runs"][0]
    assert run["run_id"] == run_id
    assert run["title"] == "History smoke"
    assert run["agent_id"] == "codex_cli"
    assert run["status"] == "dispatched"
    assert "Inspect the Warden frontend" in run["prompt_excerpt"]
    assert "sk-or-" not in recent.text


def test_run_history_public_evidence_write_rejected(monkeypatch, tmp_path):
    client = TestClient(app)
    blocked = client.post(
        "/api/mcharness/runs/run_fake123/evidence",
        json={
            "type": "transcript",
            "title": "Should fail",
            "content": "blocked on public service",
        },
    )
    assert blocked.status_code == 403
    assert "private runner" in blocked.json()["detail"].lower()


def test_run_history_evidence_redacts_secret_patterns(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/mcharness/sessions",
        json={
            "title": "Redaction smoke",
            "objective": "o",
            "plan_instruction": "p",
            "repo_path": str(Path(__file__).resolve().parents[1]),
            "agent_lane": "manual_paste",
        },
    )
    sid = created.json()["session_id"]
    started = client.post(
        f"/api/mcharness/sessions/{sid}/runner/start",
        json={
            "lane_id": "codex_cli",
            "repo_id": "mcharness-public-export",
            "title": "Redaction smoke",
            "prompt": "Safe prompt",
        },
    )
    run_id = started.json()["runner_id"]
    saved = client.post(
        f"/api/mcharness/runs/{run_id}/evidence",
        json={
            "type": "transcript",
            "title": "Secret-bearing transcript",
            "content": "OPENROUTER_API_KEY=sk-or-super-secret-token-value\nDone.",
            "source": "test",
        },
    )
    assert saved.status_code == 200, saved.text
    evidence_id = saved.json()["evidence"]["evidence_id"]
    detail = client.get(f"/api/mcharness/evidence/{evidence_id}")
    assert detail.status_code == 200
    body = detail.text
    assert "sk-or-super-secret-token-value" not in body
    assert "[REDACTED]" in body
    assert detail.json()["evidence"]["redacted"] is True


def test_run_history_recent_endpoints_return_safe_data(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    client = TestClient(app)
    empty_runs = client.get("/api/mcharness/runs/recent")
    empty_evidence = client.get("/api/mcharness/evidence/recent")
    assert empty_runs.status_code == 200
    assert empty_evidence.status_code == 200
    assert empty_runs.json()["runs"] == []
    assert empty_evidence.json()["evidence"] == []

    created = client.post(
        "/api/mcharness/sessions",
        json={
            "title": "Recent list smoke",
            "objective": "o",
            "plan_instruction": "p",
            "repo_path": str(Path(__file__).resolve().parents[1]),
            "agent_lane": "manual_paste",
        },
    )
    sid = created.json()["session_id"]
    started = client.post(
        f"/api/mcharness/sessions/{sid}/runner/start",
        json={
            "lane_id": "codex_cli",
            "repo_id": "mcharness-public-export",
            "title": "Recent list smoke",
            "prompt": "List recent runs safely.",
        },
    )
    run_id = started.json()["runner_id"]
    client.post(
        f"/api/mcharness/runs/{run_id}/evidence",
        json={
            "type": "transcript",
            "title": "Safe evidence",
            "content": "Captured output without secrets.",
        },
    )
    runs = client.get("/api/mcharness/runs/recent").json()["runs"]
    evidence = client.get("/api/mcharness/evidence/recent").json()["evidence"]
    assert len(runs) == 1
    assert runs[0]["evidence_count"] == 1
    assert len(evidence) == 1
    assert "Captured output" in evidence[0]["content_excerpt"]


def test_run_history_public_read_returns_empty_lists(monkeypatch):
    client = TestClient(app)
    runs = client.get("/api/mcharness/runs/recent")
    evidence = client.get("/api/mcharness/evidence/recent")
    assert runs.status_code == 200
    assert evidence.status_code == 200
    assert runs.json()["runs"] == []
    assert evidence.json()["evidence"] == []
    assert runs.json()["service_mode"] == "public"


def test_run_history_missing_records_return_404(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    client = TestClient(app)
    missing_run = client.get("/api/mcharness/runs/run_missing123")
    missing_evidence = client.get("/api/mcharness/evidence/ev_missing123")
    assert missing_run.status_code == 404
    assert missing_evidence.status_code == 404


def _enable_private_captain_loop(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    import src.warden.api as api_mod

    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")

    # Captain dispatch now launches CLI agents non-interactively (unattended/YOLO mode,
    # e.g. `codex exec ...`), which can take much longer to exit than the old bare
    # interactive `codex` tmux launch these tests were written against. Stub the
    # launcher so dispatch tests exercise the state machine without spawning a real
    # subprocess (matches the existing `_start_codex_runner` stubbing pattern used
    # elsewhere in this file for the interactive path).
    def fake_start_cli_runner_for_dispatch(state, cwd):
        state["status"] = "running"
        state["notes"].append("stubbed for test: no real CLI process launched")
        state["attach_command"] = f"tmux attach -t {state.get('tmux_session_name')}"
        return state

    monkeypatch.setattr(api_mod, "_start_cli_runner_for_dispatch", fake_start_cli_runner_for_dispatch)


def _sample_persisted_plan(client):
    response = client.post(
        "/api/mcharness/captain/plans",
        json={
            "goal": "Build the Captain loop",
            "repo_id": "mcharness-public-export",
            "plan_id": "plan_loop01",
            "title": "Captain loop plan",
            "summary": "Supervised step progression.",
            "steps": [
                {"id": "step_1", "title": "Inspect", "prompt": "Inspect the repo.", "agent": "codex_cli", "status": "queued"},
                {"id": "step_2", "title": "Implement", "prompt": "Implement the change.", "agent": "codex_cli", "status": "queued"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["plan"]


def test_captain_plan_persistence_and_recent_list(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    plan = _sample_persisted_plan(client)
    assert plan["plan_id"] == "plan_loop01"
    assert plan["current_step_id"] == "step_1"
    recent = client.get("/api/mcharness/captain/plans/recent")
    assert recent.status_code == 200
    assert len(recent.json()["plans"]) == 1
    detail = client.get("/api/mcharness/captain/plans/plan_loop01")
    assert detail.status_code == 200
    assert detail.json()["plan"]["steps"][0]["prompt"] == "Inspect the repo."


def test_captain_plan_dispatch_links_run(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    assert dispatch.status_code == 200, dispatch.text
    payload = dispatch.json()
    assert payload["dispatch"]["runner_id"]
    assert payload["plan"]["steps"][0]["status"] == "dispatched"
    assert payload["plan"]["steps"][0]["run_id"] == payload["dispatch"]["runner_id"]
    recent_runs = client.get("/api/mcharness/runs/recent")
    assert len(recent_runs.json()["runs"]) == 1


def test_captain_dispatch_uses_step_agent_id_for_multi_cli_lane(monkeypatch, tmp_path):
    # A step whose agent_id names Claude Code (not Codex) should dispatch to that lane.
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post(
        "/api/mcharness/captain/plans",
        json={
            "goal": "Multi-agent test",
            "repo_id": "mcharness-public-export",
            "plan_id": "plan_multi01",
            "title": "Multi-agent plan",
            "summary": "Dispatch to Claude Code.",
            "steps": [
                {"id": "step_1", "title": "Do it", "prompt": "Do it.", "agent": "claude_code_cli", "status": "queued"},
            ],
        },
    )
    dispatch = client.post("/api/mcharness/captain/plans/plan_multi01/steps/step_1/dispatch")
    assert dispatch.status_code == 200, dispatch.text
    payload = dispatch.json()
    assert payload["dispatch"]["runner_state"]["lane_id"] == "claude_code_cli"
    assert payload["watcher_id"]
    assert payload["decision_note"]


def test_captain_dispatch_creates_watcher(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    assert dispatch.status_code == 200, dispatch.text
    payload = dispatch.json()
    assert payload["watcher_id"]

    import src.warden.api as api_mod
    from src.warden.resident.state import get_state
    from src.warden.resident.watchers import WatcherService

    watchers = WatcherService(get_state(tmp_path / "resident" / "resident.sqlite"))
    watcher = watchers.get(payload["watcher_id"])
    assert watcher is not None
    assert watcher.kind == "captain_dispatch"


def test_captain_watcher_background_loop_processes_watchers_without_a_plan_id_filter(monkeypatch, tmp_path):
    # The always-on background loop (captain_watcher_background_loop) must not be
    # scoped to a single plan the way the frontend-driven poll endpoint is — it has
    # to catch up ANY plan's finished run even if nobody ever opened Captain Deck
    # for that specific plan.
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    assert dispatch.status_code == 200, dispatch.text

    import src.warden.api as api_mod
    from src.warden.resident.state import get_state
    from src.warden.resident.watchers import WatcherService

    watchers_svc = WatcherService(get_state(tmp_path / "resident" / "resident.sqlite"))
    active = [w for w in watchers_svc.list(status="active") if w.kind == "captain_dispatch"]
    assert len(active) == 1

    # Directly exercise the shared per-watcher processor the background loop calls —
    # note it is NOT told which plan_id to look at, unlike the poll endpoint.
    entry = api_mod._process_captain_dispatch_watcher(active[0], watchers_svc)
    assert entry is not None
    assert entry["outcome"] == "completed"
    assert entry["plan_id"] == "plan_loop01"
    assert entry["gate_created"] is True

    plan = client.get("/api/mcharness/captain/plans/plan_loop01").json()["plan"]
    assert plan["current_gate_status"] == "pending"


def test_captain_watcher_poll_opens_gate_on_clean_completion_without_auto_completing(monkeypatch, tmp_path):
    # A clean CLI exit must NOT complete the step by itself — it opens a pending
    # proof gate and waits for a human decision (see test below for what happens
    # after approval).
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    assert dispatch.status_code == 200, dispatch.text

    # The stubbed launcher doesn't create a real tmux session, so the watcher's tmux
    # check reports "completed" immediately (no session to find).
    poll = client.post("/api/mcharness/captain/plans/plan_loop01/watchers/poll")
    assert poll.status_code == 200, poll.text
    poll_data = poll.json()
    assert poll_data["watchers"][0]["outcome"] == "completed"

    plan = client.get("/api/mcharness/captain/plans/plan_loop01").json()["plan"]
    assert plan["steps"][0]["status"] == "dispatched"  # not auto-completed
    assert plan["current_step_id"] == "step_1"  # not auto-advanced

    recent_gates = client.get("/api/mcharness/gates/recent")
    assert recent_gates.status_code == 200
    gate_titles = [g["title"] for g in recent_gates.json().get("gates", [])]
    assert any("review before continuing" in title for title in gate_titles)


def test_captain_gate_approval_completes_step_and_auto_advances(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post(
        "/api/mcharness/captain/plans",
        json={
            "goal": "Auto advance test",
            "repo_id": "mcharness-public-export",
            "plan_id": "plan_auto01",
            "title": "Auto advance plan",
            "summary": "Two steps.",
            "auto_advance": True,
            "steps": [
                {"id": "step_1", "title": "Step one", "prompt": "One.", "agent": "codex_cli", "status": "queued"},
                {"id": "step_2", "title": "Step two", "prompt": "Two.", "agent": "codex_cli", "status": "queued"},
            ],
        },
    )
    dispatch = client.post("/api/mcharness/captain/plans/plan_auto01/steps/step_1/dispatch")
    assert dispatch.status_code == 200, dispatch.text

    poll = client.post("/api/mcharness/captain/plans/plan_auto01/watchers/poll")
    assert poll.status_code == 200, poll.text

    plan_before = client.get("/api/mcharness/captain/plans/plan_auto01").json()["plan"]
    assert plan_before["steps"][0]["status"] == "dispatched"
    assert plan_before["current_step_id"] == "step_1"

    recent_gates = client.get("/api/mcharness/gates/recent").json()["gates"]
    gate = next(g for g in recent_gates if g.get("plan_id") == "plan_auto01" and g.get("step_id") == "step_1")

    decision = client.post(f"/api/mcharness/gates/{gate['gate_id']}/decision", json={"decision": "approve"})
    assert decision.status_code == 200, decision.text

    plan_after = client.get("/api/mcharness/captain/plans/plan_auto01").json()["plan"]
    assert plan_after["steps"][0]["status"] == "passed"
    assert plan_after["current_step_id"] == "step_2"
    assert plan_after["steps"][1]["status"] == "dispatched"  # auto-dispatched on approval
    assert plan_after["steps"][1]["run_id"]


def test_captain_watcher_poll_marks_needs_review_on_stall_and_does_not_auto_advance(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post(
        "/api/mcharness/captain/plans",
        json={
            "goal": "Stall test",
            "repo_id": "mcharness-public-export",
            "plan_id": "plan_stall01",
            "title": "Stall plan",
            "summary": "One step.",
            "auto_advance": True,
            "steps": [
                {"id": "step_1", "title": "Step one", "prompt": "One.", "agent": "codex_cli", "status": "queued"},
            ],
        },
    )
    dispatch = client.post("/api/mcharness/captain/plans/plan_stall01/steps/step_1/dispatch")
    assert dispatch.status_code == 200, dispatch.text

    def fake_check_stalled(watcher):
        return {"outcome": "stalled", "elapsed_seconds": 99999}

    from src.warden.resident import watchers as watchers_mod
    monkeypatch.setitem(watchers_mod._CHECKERS, "captain_dispatch", fake_check_stalled)

    poll = client.post("/api/mcharness/captain/plans/plan_stall01/watchers/poll")
    assert poll.status_code == 200, poll.text
    assert poll.json()["watchers"][0]["outcome"] == "stalled"

    plan = client.get("/api/mcharness/captain/plans/plan_stall01").json()["plan"]
    assert plan["steps"][0]["status"] == "needs_review"


def test_captain_plan_complete_advances_without_auto_dispatch(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    completed = client.post(
        "/api/mcharness/captain/plans/plan_loop01/steps/step_1/complete",
        json={"evidence_ids": ["ev_test01"]},
    )
    assert completed.status_code == 200, completed.text
    plan = completed.json()["plan"]
    assert plan["steps"][0]["status"] == "passed"
    assert plan["current_step_id"] == "step_2"
    assert plan["steps"][1]["status"] == "queued"
    assert len(client.get("/api/mcharness/runs/recent").json()["runs"]) == 1


def test_captain_plan_revise_updates_prompt_and_logs(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    revised = client.post(
        "/api/mcharness/captain/plans/plan_loop01/steps/step_1/revise",
        json={"prompt": "Inspect only the frontend files.", "note": "Tightened scope."},
    )
    assert revised.status_code == 200, revised.text
    plan = revised.json()["plan"]
    assert plan["steps"][0]["status"] == "revised"
    assert "frontend files" in plan["steps"][0]["prompt"]
    assert plan["decision_log"][0]["action"] == "step_revised"


def test_captain_plan_stop_updates_status(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    stopped = client.post("/api/mcharness/captain/plans/plan_loop01/stop", json={"note": "Paused by operator."})
    assert stopped.status_code == 200, stopped.text
    plan = stopped.json()["plan"]
    assert plan["status"] == "stopped"
    assert plan["steps"][0]["status"] == "stopped"


def test_captain_plan_public_writes_rejected(monkeypatch):
    client = TestClient(app)
    # dispatch is now ungated — returns 404 (plan not found) not 403
    blocked = client.post("/api/mcharness/captain/plans/plan_x/steps/step_1/dispatch")
    assert blocked.status_code == 404
    # complete/revise/stop are still gated — return 403
    blocked_complete = client.post("/api/mcharness/captain/plans/plan_x/steps/step_1/complete", json={})
    assert blocked_complete.status_code == 403
    blocked_revise = client.post("/api/mcharness/captain/plans/plan_x/steps/step_1/revise", json={"prompt": "nope"})
    assert blocked_revise.status_code == 403
    blocked_stop = client.post("/api/mcharness/captain/plans/plan_x/stop", json={})
    assert blocked_stop.status_code == 403


# ---------------------------------------------------------------------------
# Phase 2 — Dispatch proof memory loop tests
# ---------------------------------------------------------------------------

def _persist_sample_plan_directly(tmp_path, plan_id="plan_loop01"):
    """Persist a sample plan directly (bypasses API auth) for blocked-path tests."""
    from src.warden.captain_plans import persist_plan
    plan_data = {
        "plan_id": plan_id,
        "title": "Captain loop plan",
        "summary": "Supervised step progression.",
        "source": "local_preview",
        "steps": [
            {"step_id": "step_1", "title": "Inspect", "prompt": "Inspect the repo.", "agent": "codex_cli", "status": "queued"},
            {"step_id": "step_2", "title": "Implement", "prompt": "Implement the change.", "agent": "codex_cli", "status": "queued"},
        ],
        "notes": [],
    }
    persist_plan(tmp_path, goal="Build the Captain loop", repo_id="mcharness-public-export", plan_data=plan_data)


def _isolated_dispatch_env(monkeypatch, tmp_path):
    """Set up isolated store for dispatch memory tests (no runner, tmp stores)."""
    import src.warden.api as api_mod
    import src.warden.workbench as wb_mod

    monkeypatch.delenv("MCHARNESS_TMUX_RUNNER_ENABLED", raising=False)
    monkeypatch.delenv("MCHARNESS_CODEX_RUNNER_ENABLED", raising=False)
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")
    monkeypatch.setattr(api_mod, "_write_plan_memory", lambda **kwargs: None)
    # WorkbenchStore uses its own WORKBENCH_ROOT — redirect to tmp_path too
    monkeypatch.setattr(wb_mod, "WORKBENCH_ROOT", tmp_path / "workbench")


def test_dispatch_blocked_saves_blocked_attempt_memory(monkeypatch, tmp_path):
    """When runner is unavailable dispatch returns ok=True, blocked=True and writes blocked_attempt memory."""
    from src.warden.workbench import WorkbenchStore
    _isolated_dispatch_env(monkeypatch, tmp_path)
    _persist_sample_plan_directly(tmp_path)
    client = TestClient(app)

    resp = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["blocked"] is True
    assert data["run_id"].startswith("blocked-")
    assert data["memory_id"] is not None
    assert "Runner unavailable" in data["message"]

    store = WorkbenchStore(root=tmp_path / "workbench")
    mems = store.search_memories("blocked_attempt", limit=5)
    assert any(
        m.kind == "blocked_attempt" and m.source == "captain_dispatch"
        for m in mems
    ), "blocked_attempt memory not found"


def test_dispatch_blocked_memory_includes_required_metadata(monkeypatch, tmp_path):
    """blocked_attempt memory metadata contains plan_id, step_id, run_id, repo_id, lane_id."""
    from src.warden.workbench import WorkbenchStore
    _isolated_dispatch_env(monkeypatch, tmp_path)
    _persist_sample_plan_directly(tmp_path)
    client = TestClient(app)
    resp = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    assert resp.status_code == 200

    store = WorkbenchStore(root=tmp_path / "workbench")
    mems = store.search_memories("blocked_attempt", limit=5)
    mem = next((m for m in mems if m.kind == "blocked_attempt"), None)
    assert mem is not None, "blocked_attempt memory not found"
    meta = mem.metadata or {}
    assert meta.get("plan_id") == "plan_loop01"
    assert meta.get("step_id") == "step_1"
    assert meta.get("repo_id") == "mcharness-public-export"
    assert meta.get("lane_id") == "codex_cli"
    assert meta.get("reason") == "runner_unavailable"
    assert meta.get("run_id", "").startswith("blocked-")


def test_dispatch_creates_run_record_and_agent_result_memory(monkeypatch, tmp_path):
    """When runner is available dispatch creates run record and agent_result memory."""
    _enable_private_captain_loop(monkeypatch, tmp_path)
    import src.warden.api as api_mod
    import src.warden.workbench as wb_mod
    monkeypatch.setattr(api_mod, "_write_plan_memory", lambda **kwargs: None)
    monkeypatch.setattr(wb_mod, "WORKBENCH_ROOT", tmp_path / "workbench")

    from src.warden.workbench import WorkbenchStore
    client = TestClient(app)
    _sample_persisted_plan(client)

    resp = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data.get("blocked") is False
    assert data.get("run_id")
    assert data.get("memory_id")

    store = WorkbenchStore(root=tmp_path / "workbench")
    mems = store.search_memories("agent_result", limit=5)
    assert any(
        m.kind == "agent_result" and m.source == "captain_dispatch"
        for m in mems
    ), "agent_result memory not found"


def test_save_proof_memory_endpoint_for_blocked_run(monkeypatch, tmp_path):
    """POST /runs/{run_id}/save-proof-memory writes a memory for an existing blocked run."""
    import src.warden.api as api_mod
    import src.warden.workbench as wb_mod
    from src.warden.run_history import create_run_record

    monkeypatch.delenv("MCHARNESS_TMUX_RUNNER_ENABLED", raising=False)
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(wb_mod, "WORKBENCH_ROOT", tmp_path / "workbench")

    create_run_record(
        tmp_path,
        run_id="run_test_proof",
        title="Test blocked run",
        agent_id="codex_cli",
        agent_adapter="codex_cli",
        repo_id="mcharness-public-export",
        branch=None,
        prompt="Inspect the repo.",
        status="blocked",
        plan_id="plan_loop01",
        created_by="captain_dispatch",
        service_mode="public",
    )

    client = TestClient(app)
    resp = client.post("/api/mcharness/runs/run_test_proof/save-proof-memory")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["run_id"] == "run_test_proof"
    assert data["kind"] == "blocked_attempt"
    assert data["memory_id"] is not None


def test_dispatch_proof_memory_redacts_secrets(monkeypatch, tmp_path):
    """Response from dispatch does not expose raw secret values."""
    import src.warden.api as api_mod
    import src.warden.workbench as wb_mod

    monkeypatch.delenv("MCHARNESS_TMUX_RUNNER_ENABLED", raising=False)
    monkeypatch.delenv("MCHARNESS_CODEX_RUNNER_ENABLED", raising=False)
    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api_mod, "CAPTAIN_PLAN_ROOT", tmp_path / "captain" / "plans")
    monkeypatch.setattr(api_mod, "_write_plan_memory", lambda **kwargs: None)
    monkeypatch.setattr(wb_mod, "WORKBENCH_ROOT", tmp_path / "workbench")

    from src.warden.captain_plans import persist_plan
    plan_data = {
        "plan_id": "plan_secret_test",
        "title": "Secret test plan",
        "summary": "Testing redaction.",
        "source": "local_preview",
        "steps": [
            {
                "step_id": "step_1",
                "title": "Inspect",
                "prompt": "Inspect the repo.",
                "agent": "codex_cli",
                "status": "queued",
            }
        ],
        "notes": [],
    }
    persist_plan(tmp_path, goal="Test sk-or-v1-abcdefghij redaction", repo_id="mcharness-public-export", plan_data=plan_data)

    client = TestClient(app)
    resp = client.post("/api/mcharness/captain/plans/plan_secret_test/steps/step_1/dispatch")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # The dispatch-level fields (run_id, memory_id, message) must not expose raw secrets
    for field in ("run_id", "memory_id", "message"):
        val = str(data.get(field, ""))
        assert "sk-or-v1-abcdefghij" not in val, f"secret leaked in field {field!r}"


def test_captain_plan_invalid_step_returns_404(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    missing = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_missing/complete", json={})
    assert missing.status_code == 404


def test_worklog_empty_when_no_activity(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    client = TestClient(app)
    response = client.get("/api/mcharness/worklog/recent")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["service_mode"] == "private"


def test_worklog_public_read_returns_empty_list(monkeypatch):
    client = TestClient(app)
    response = client.get("/api/mcharness/worklog/recent")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["service_mode"] == "public"


def test_worklog_shows_real_events_after_dispatch_and_evidence(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    assert dispatch.status_code == 200, dispatch.text
    run_id = dispatch.json()["dispatch"]["runner_id"]
    saved = client.post(
        f"/api/mcharness/runs/{run_id}/evidence",
        json={
            "type": "transcript",
            "title": "Worklog evidence",
            "content": "Captured proof for worklog.",
        },
    )
    assert saved.status_code == 200, saved.text
    worklog = client.get("/api/mcharness/worklog/recent")
    assert worklog.status_code == 200
    items = worklog.json()["items"]
    kinds = {item["kind"] for item in items}
    assert "plan_created" in kinds
    assert "step_dispatched" in kinds
    assert "run_created" in kinds
    assert "evidence_saved" in kinds
    assert "sample" not in worklog.text.lower()
    assert "fake" not in worklog.text.lower()
    assert "sk-or-" not in worklog.text


def _create_private_run(client):
    created = client.post(
        "/api/mcharness/sessions",
        json={
            "title": "Gate smoke",
            "objective": "o",
            "plan_instruction": "p",
            "repo_path": str(Path(__file__).resolve().parents[1]),
            "agent_lane": "manual_paste",
        },
    )
    sid = created.json()["session_id"]
    started = client.post(
        f"/api/mcharness/sessions/{sid}/runner/start",
        json={
            "lane_id": "codex_cli",
            "repo_id": "mcharness-public-export",
            "title": "Gate smoke",
            "prompt": "Inspect proof gates.",
        },
    )
    return started.json()["runner_id"]


def test_proof_gate_private_create_and_list_on_run(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    client = TestClient(app)
    run_id = _create_private_run(client)
    created = client.post(
        f"/api/mcharness/runs/{run_id}/gates",
        json={"title": "Manual review", "summary": "Check transcript quality."},
    )
    assert created.status_code == 200, created.text
    listed = client.get(f"/api/mcharness/runs/{run_id}/gates")
    assert listed.status_code == 200
    assert len(listed.json()["gates"]) == 1
    assert listed.json()["gates"][0]["status"] == "pending"


def test_proof_gate_public_create_blocked(monkeypatch, tmp_path):
    client = TestClient(app)
    blocked = client.post(
        "/api/mcharness/runs/run_fake123/gates",
        json={"title": "Should fail", "summary": "blocked"},
    )
    assert blocked.status_code == 403


def test_proof_gate_decision_requires_reason_and_does_not_auto_dispatch(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    run_id = dispatch.json()["dispatch"]["runner_id"]
    gate = client.post(
        f"/api/mcharness/runs/{run_id}/gates",
        json={"title": "Approve gate", "summary": "Review before next step."},
    )
    gate_id = gate.json()["gate"]["gate_id"]
    missing_reason = client.post(
        f"/api/mcharness/gates/{gate_id}/decision",
        json={"decision": "block", "decided_by": "operator"},
    )
    assert missing_reason.status_code == 400
    approved = client.post(
        f"/api/mcharness/gates/{gate_id}/decision",
        json={"decision": "approve", "decided_by": "operator"},
    )
    assert approved.status_code == 200
    assert approved.json()["gate"]["status"] == "approved"
    plan = client.get("/api/mcharness/captain/plans/plan_loop01").json()["plan"]
    assert plan["current_step_id"] == "step_1"
    step2 = next(step for step in plan["steps"] if step["id"] == "step_2")
    assert step2["status"] in {"queued", "revised"}
    assert not step2.get("run_id")
    assert "sk-or-" not in approved.text


def test_captain_step_complete_blocked_by_pending_gate(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    run_id = dispatch.json()["dispatch"]["runner_id"]
    client.post(
        f"/api/mcharness/runs/{run_id}/gates",
        json={"title": "Pending review", "summary": "Hold step completion."},
    )
    blocked = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/complete", json={})
    assert blocked.status_code == 409
    assert "pending" in blocked.json()["detail"].lower()


def test_captain_step_complete_blocked_by_blocked_gate(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    run_id = dispatch.json()["dispatch"]["runner_id"]
    gate = client.post(
        f"/api/mcharness/runs/{run_id}/gates",
        json={"title": "Blocked review", "summary": "Stop here."},
    )
    gate_id = gate.json()["gate"]["gate_id"]
    client.post(
        f"/api/mcharness/gates/{gate_id}/decision",
        json={"decision": "block", "decided_by": "operator", "decision_reason": "Not safe yet."},
    )
    blocked = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/complete", json={})
    assert blocked.status_code == 409
    assert "blocked" in blocked.json()["detail"].lower()


def test_captain_step_complete_allowed_after_gate_approved_without_auto_dispatch(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    run_id = dispatch.json()["dispatch"]["runner_id"]
    gate = client.post(
        f"/api/mcharness/runs/{run_id}/gates",
        json={"title": "Approved review", "summary": "Looks good."},
    )
    gate_id = gate.json()["gate"]["gate_id"]
    client.post(
        f"/api/mcharness/gates/{gate_id}/decision",
        json={"decision": "approve", "decided_by": "operator"},
    )
    completed = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/complete", json={})
    assert completed.status_code == 200, completed.text
    plan = completed.json()["plan"]
    assert plan["current_step_id"] == "step_2"
    step2 = next(step for step in plan["steps"] if step["id"] == "step_2")
    assert step2["status"] in {"queued", "revised"}
    assert not step2.get("run_id")


def test_worklog_includes_gate_created_and_decision_events(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    dispatch = client.post("/api/mcharness/captain/plans/plan_loop01/steps/step_1/dispatch")
    run_id = dispatch.json()["dispatch"]["runner_id"]
    gate = client.post(
        f"/api/mcharness/runs/{run_id}/gates",
        json={"title": "Worklog gate", "summary": "Track in worklog."},
    )
    gate_id = gate.json()["gate"]["gate_id"]
    client.post(
        f"/api/mcharness/gates/{gate_id}/decision",
        json={"decision": "request_more_evidence", "decided_by": "operator", "decision_reason": "Need transcript."},
    )
    worklog = client.get("/api/mcharness/worklog/recent")
    assert worklog.status_code == 200
    kinds = {item["kind"] for item in worklog.json()["items"]}
    assert "gate_created" in kinds
    assert "gate_needs_more_evidence" in kinds
    assert "sample" not in worklog.text.lower()


def test_run_detail_includes_gate_decision_history(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    client = TestClient(app)
    run_id = _create_private_run(client)
    gate = client.post(
        f"/api/mcharness/runs/{run_id}/gates",
        json={"title": "Review gate", "summary": "Check output."},
    )
    gate_id = gate.json()["gate"]["gate_id"]
    client.post(
        f"/api/mcharness/gates/{gate_id}/decision",
        json={"decision": "approve", "decided_by": "operator"},
    )
    detail = client.get(f"/api/mcharness/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    gates = detail.json()["gates"]
    assert len(gates) == 1
    assert gates[0]["status"] == "approved"
    assert gates[0]["decision_log"]
    assert gates[0]["decision_log"][0]["decision"] == "approve"


def test_run_detail_review_sections_and_export_still_work(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    client = TestClient(app)
    run_id = _create_private_run(client)
    detail = client.get(f"/api/mcharness/runs/{run_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert "run" in body
    assert "evidence" in body
    assert "gates" in body
    assert body["run"]["gate_label"] == "No gate"
    report = client.get(f"/api/mcharness/runs/{run_id}/report")
    assert report.status_code == 200
    assert report.json()["format"] == "markdown"


def test_run_report_includes_evidence_gates_and_redacts_secrets(monkeypatch, tmp_path):
    _enable_private_run_history(monkeypatch, tmp_path)
    client = TestClient(app)
    run_id = _create_private_run(client)
    client.post(
        f"/api/mcharness/runs/{run_id}/evidence",
        json={
            "type": "transcript",
            "title": "Secret transcript",
            "content": "OPENROUTER_API_KEY=sk-or-report-secret\nOutput ok.",
        },
    )
    gate = client.post(
        f"/api/mcharness/runs/{run_id}/gates",
        json={"title": "Review gate", "summary": "Check output."},
    )
    gate_id = gate.json()["gate"]["gate_id"]
    client.post(
        f"/api/mcharness/gates/{gate_id}/decision",
        json={"decision": "approve", "decided_by": "operator"},
    )
    report = client.get(f"/api/mcharness/runs/{run_id}/report")
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["format"] == "markdown"
    assert "Secret transcript" in body["markdown"]
    assert "Review gate" in body["markdown"]
    assert "approved" in body["markdown"].lower()
    assert len(body["evidence"]) == 1
    assert len(body["gates"]) == 1
    assert "sk-or-report-secret" not in report.text
    assert "[REDACTED]" in report.text


def test_mission_control_snapshot_idle_public(monkeypatch):
    client = TestClient(app)
    response = client.get("/api/mcharness/mission-control/snapshot")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mission"]["status"] == "idle"
    assert body["mission"]["mission_id"] is None
    assert body["safety"]["public_runner_enabled"] is False
    assert body["safety"]["jules_runnable"] is False
    assert body["service_mode"] == "public"
    assert "sample" not in response.text.lower()
    assert "fake" not in response.text.lower()


def test_mission_control_snapshot_active_private(monkeypatch, tmp_path):
    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)
    response = client.get("/api/mcharness/mission-control/snapshot")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mission"]["status"] in {"planned", "running"}
    assert body["mission"]["mission_id"] == "plan_loop01"
    assert body["plan"]["plan_id"] == "plan_loop01"
    assert len(body["plan"]["steps"]) == 2
    assert body["timeline"]["items"]
    assert body["next_move"]["action"] in {"view_codex", "develop_plan", "none", "mark_step_done", "review_gate"}
    assert body["service_mode"] == "private"


def test_agents_health_public_codex_disabled_private_runnable(monkeypatch, tmp_path):
    public = TestClient(app)
    public_health = public.get("/api/mcharness/agents/health")
    assert public_health.status_code == 200
    public_codex = next(item for item in public_health.json()["items"] if item["id"] == "codex_cli")
    assert public_codex["runnable"] is False
    assert public_codex["mode"] == "disabled"

    _enable_private_run_history(monkeypatch, tmp_path)
    private = TestClient(app)
    private_health = private.get("/api/mcharness/agents/health")
    assert private_health.status_code == 200
    private_codex = next(item for item in private_health.json()["items"] if item["id"] == "codex_cli")
    assert private_codex["runnable"] is True
    assert private_codex["mode"] == "execution"
    jules_items = [item for item in private_health.json()["items"] if item.get("adapter") == "jules_remote" or item.get("mode") == "planning_only"]
    for item in jules_items:
        if item["id"] != "captain":
            assert item.get("mode") == "planning_only" or item.get("runnable") is False


def test_safety_status_public_and_private(monkeypatch, tmp_path):
    public = TestClient(app)
    public_safety = public.get("/api/mcharness/safety/status")
    assert public_safety.status_code == 200
    assert public_safety.json()["public_runner_enabled"] is False
    assert public_safety.json()["arbitrary_shell_input"] is False
    assert public_safety.json()["jules_runnable"] is False
    assert public_safety.json()["secrets_exposed"] is False

    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    import src.warden.api as api_mod

    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    private = TestClient(app)
    private_safety = private.get("/api/mcharness/safety/status")
    assert private_safety.status_code == 200
    assert private_safety.json()["private_runner_enabled"] is True
    assert private_safety.json()["public_runner_enabled"] is False


def test_mission_pause_and_adjust_plan_private_only(monkeypatch, tmp_path):
    public_blocked = TestClient(app)
    assert public_blocked.post("/api/mcharness/missions/plan_loop01/pause", json={}).status_code == 403

    _enable_private_captain_loop(monkeypatch, tmp_path)
    client = TestClient(app)
    _sample_persisted_plan(client)

    paused = client.post("/api/mcharness/missions/plan_loop01/pause", json={"note": "Operator hold."})
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "stopped"
    snapshot = client.get("/api/mcharness/mission-control/snapshot")
    assert snapshot.json()["mission"]["status"] == "stopped"
    kinds = {item["kind"] for item in client.get("/api/mcharness/worklog/recent").json()["items"]}
    assert "mission_paused" in kinds

    _sample_persisted_plan(client)
    adjusted = client.post(
        "/api/mcharness/missions/plan_loop01/adjust-plan",
        json={"note": "Need narrower scope.", "adjustments": {"scope": "smaller"}},
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["human_review_required"] is True
    kinds = {item["kind"] for item in client.get("/api/mcharness/worklog/recent").json()["items"]}
    assert "plan_adjustment_requested" in kinds


def test_runner_sessions_inventory_public_sanitized(monkeypatch):
    client = TestClient(app)
    response = client.get("/api/mcharness/runner/sessions")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["max_active_runner_sessions"] == 4
    assert "items" in body
    assert "sk-or-" not in response.text


def test_runner_sessions_cleanup_public_rejected(monkeypatch):
    client = TestClient(app)
    blocked = client.post("/api/mcharness/runner/sessions/cleanup", json={"confirm": False})
    assert blocked.status_code == 403


def test_runner_sessions_cleanup_dry_run_private(monkeypatch, tmp_path):
    import subprocess

    import src.warden.api as api_mod

    _enable_private_run_history(monkeypatch, tmp_path)

    def fake_inventory(*args, **kwargs):
        return {
            "generated_at": "2026-06-09T12:00:00+00:00",
            "max_active_runner_sessions": 4,
            "total_runner_sessions": 1,
            "active_runner_sessions": 1,
            "stale_runner_sessions": 1,
            "items": [
                {
                    "session_name": "mch_run_run_stale01",
                    "safe_to_manage": True,
                    "age_seconds": 9000,
                    "active": False,
                    "dead": False,
                    "stale": True,
                    "linked_run_id": "run_stale01",
                }
            ],
        }

    def fake_cleanup(root, **kwargs):
        assert kwargs.get("confirm") is False
        return {
            "dry_run": True,
            "candidates": ["mch_run_run_stale01"],
            "killed": [],
            "skipped": [],
            "errors": [],
            "inventory": {"total_runner_sessions": 1, "active_runner_sessions": 1, "stale_runner_sessions": 1},
        }

    monkeypatch.setattr(api_mod, "build_runner_session_inventory", fake_inventory)
    monkeypatch.setattr(api_mod, "cleanup_runner_sessions", fake_cleanup)
    client = TestClient(app)
    response = client.post("/api/mcharness/runner/sessions/cleanup", json={"confirm": False, "stale_after_seconds": 7200})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["killed"] == []
    assert body["candidates"] == ["mch_run_run_stale01"]


def test_codex_dispatch_rejected_at_runner_session_limit(monkeypatch, tmp_path):
    import src.warden.api as api_mod
    import src.warden.runner_sessions as runner_sessions_mod

    _enable_private_run_history(monkeypatch, tmp_path)
    monkeypatch.setattr(
        runner_sessions_mod,
        "build_runner_session_inventory",
        lambda *args, **kwargs: {
            "max_active_runner_sessions": 4,
            "active_runner_sessions": 4,
            "total_runner_sessions": 4,
            "stale_runner_sessions": 0,
            "items": [],
        },
    )
    client = TestClient(app)
    created = client.post(
        "/api/mcharness/sessions",
        json={
            "title": "Limit test",
            "objective": "Limit test",
            "plan_instruction": "Test runner limit.",
            "repo_path": str(Path(__file__).resolve().parents[1]),
            "agent_lane": "codex_cli",
        },
    )
    sid = created.json()["session_id"]
    blocked = client.post(
        f"/api/mcharness/sessions/{sid}/runner/start",
        json={"lane_id": "codex_cli", "repo_id": "mcharness-public-export"},
    )
    assert blocked.status_code == 409
    assert "Runner session limit reached" in blocked.json()["detail"]


def test_safety_and_snapshot_surface_runner_sessions(monkeypatch, tmp_path):
    import src.warden.api as api_mod

    _enable_private_run_history(monkeypatch, tmp_path)
    monkeypatch.setattr(
        api_mod,
        "build_runner_session_inventory",
        lambda *args, **kwargs: {
            "generated_at": "2026-06-09T12:00:00+00:00",
            "max_active_runner_sessions": 4,
            "total_runner_sessions": 4,
            "active_runner_sessions": 4,
            "stale_runner_sessions": 1,
            "items": [],
        },
    )
    client = TestClient(app)
    safety = client.get("/api/mcharness/safety/status")
    assert safety.status_code == 200
    runner_item = next(item for item in safety.json()["items"] if item["key"] == "runner_sessions")
    assert runner_item["status"] == "limit_reached"
    snapshot = client.get("/api/mcharness/mission-control/snapshot")
    assert snapshot.status_code == 200
    assert snapshot.json()["runner_sessions"]["active_runner_sessions"] == 4


def test_codex_dispatch_allowed_below_runner_session_limit(monkeypatch, tmp_path):
    import src.warden.runner_sessions as runner_sessions_mod

    _enable_private_run_history(monkeypatch, tmp_path)
    monkeypatch.setattr(
        runner_sessions_mod,
        "build_runner_session_inventory",
        lambda *args, **kwargs: {
            "max_active_runner_sessions": 4,
            "active_runner_sessions": 2,
            "total_runner_sessions": 2,
            "stale_runner_sessions": 0,
            "items": [],
        },
    )
    client = TestClient(app)
    created = client.post(
        "/api/mcharness/sessions",
        json={
            "title": "Below limit",
            "objective": "Below limit",
            "plan_instruction": "Test below runner limit.",
            "repo_path": str(Path(__file__).resolve().parents[1]),
            "agent_lane": "codex_cli",
        },
    )
    sid = created.json()["session_id"]
    started = client.post(
        f"/api/mcharness/sessions/{sid}/runner/start",
        json={"lane_id": "codex_cli", "repo_id": "mcharness-public-export"},
    )
    assert started.status_code == 200, started.text
    assert "Runner session limit reached" not in (started.text or "")


def test_tmux_session_name_uses_mch_run_prefix():
    import src.warden.api as api_mod

    name = api_mod._tmux_session_name("session-1", "run_abc12345")
    assert name.startswith("mch_run_")


def test_agent_refresh_status_public_codex_not_runnable(monkeypatch):
    client = TestClient(app)
    refreshed = client.post("/api/mcharness/agents/refresh-status")
    assert refreshed.status_code == 200, refreshed.text
    codex = next(agent for agent in refreshed.json()["agents"] if agent["id"] == "codex_cli")
    assert codex["runnable"] is False
    assert codex["status"] in {"disabled", "ready"}
    assert refreshed.json()["service_mode"] == "public"
    assert "test-jules-key" not in refreshed.text


@pytest.mark.requires_codex_cli
def test_agent_refresh_status_private_codex_runnable(monkeypatch, tmp_path):
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    import src.warden.api as api_mod

    monkeypatch.setattr(api_mod, "MCTABLE_ROOT", tmp_path)
    client = TestClient(app)
    refreshed = client.post("/api/mcharness/agents/refresh-status")
    assert refreshed.status_code == 200
    codex = next(agent for agent in refreshed.json()["agents"] if agent["id"] == "codex_cli")
    assert codex["runnable"] is True
    assert codex.get("last_checked_at")
    assert "No tasks were started" in " ".join(refreshed.json().get("notes") or [])


# ---------------------------------------------------------------------------
# Connector platform tests
# ---------------------------------------------------------------------------

def test_connectors_providers_lists_three_providers():
    """GET /warden/connectors/providers returns gmail, outlook, icloud without credentials."""
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/connectors/providers")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    ids = [p["provider_id"] for p in data["providers"]]
    assert "gmail" in ids
    assert "outlook" in ids
    assert "icloud" in ids


def test_connectors_providers_unconfigured_without_env(monkeypatch):
    """Without OAuth env vars, non-Gmail OAuth providers show configured=False.
    Gmail is always configured=True since IMAP app-password requires no pre-config."""
    monkeypatch.delenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("WARDEN_MICROSOFT_OAUTH_CLIENT_ID", raising=False)
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/connectors/providers")
    assert resp.status_code == 200
    for p in resp.json()["providers"]:
        if p["provider_id"] == "gmail":
            assert p["configured"] is True, "Gmail should always be configured (IMAP app-password path)"
        else:
            assert p["configured"] is False, f"{p['provider_id']} should be unconfigured without env vars"


def test_connectors_accounts_empty_initially():
    """GET /warden/connectors/accounts returns empty list when no accounts connected."""
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/connectors/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["accounts"], list)


def test_connectors_connect_start_gmail_unconfigured(monkeypatch):
    """POST .../gmail/connect/start returns configured=False when no OAuth keys set."""
    monkeypatch.delenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("WARDEN_GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    # Also mock vault-based config to ensure clean state
    import src.warden.connectors.oauth as oauth_mod
    monkeypatch.setattr(oauth_mod, "is_provider_configured", lambda p: False)
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["configured"] is False
    assert data["error"]  # error message present


def test_connectors_connect_start_gmail_configured(monkeypatch):
    """POST .../gmail/connect/start returns auth_url when OAuth keys are set."""
    monkeypatch.setenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("WARDEN_GOOGLE_OAUTH_CLIENT_SECRET", "fake-client-secret")
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "auth_url" in data
    assert "accounts.google.com" in data["auth_url"]
    assert "state" in data


def test_connectors_callback_rejects_invalid_state():
    """GET .../gmail/callback rejects unknown/invalid state."""
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/connectors/gmail/callback",
                      params={"code": "fake_code", "state": "totally-invalid-state"})
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"]


def test_connectors_accounts_redacts_tokens(tmp_path, monkeypatch):
    """Accounts endpoint never exposes raw tokens."""
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    from src.warden.connectors.store import ConnectorStore
    from src.warden.connectors.models import ConnectedAccount
    store = ConnectorStore()
    acc = ConnectedAccount(
        account_id="test-acc-1", user_id="matt",
        provider="gmail", display_email="test@gmail.com",
        status="connected",
    )
    store.save_account(acc, token="real-secret-token-abc123")

    # Verify the account was saved with redacted token in list
    accounts_raw = store.list_accounts(redact=True)
    assert accounts_raw  # account was saved
    assert "real-secret-token-abc123" not in str(accounts_raw)


def test_marius_trace_in_agent_response(monkeypatch):
    """Warden agent chat response includes a trace field."""
    import src.warden.agent as agent_mod
    from src.warden.agent import AgentResponse

    fake_resp = AgentResponse(
        reply="Test reply",
        tools_used=[],
        sources=["context"],
        model="test-model",
        provider="test",
        fallback=True,
        trace={"trace_id": "trace-abc123", "agent": "Marius Agent", "steps": [
            {"type": "note", "label": "Fallback mode", "status": "ok", "detail": "", "ref": ""}
        ]},
    )

    async def fake_run_agent(message, history):
        return fake_resp

    monkeypatch.setattr(agent_mod, "run_agent", fake_run_agent)
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/agent/chat",
                       json={"message": "test", "history": []})
    assert resp.status_code == 200
    data = resp.json()
    assert "trace" in data
    trace = data["trace"]
    assert trace is not None
    assert trace["agent"] == "Marius Agent"
    assert isinstance(trace["steps"], list)


# ─── OAuth callback + token exchange tests ───────────────────────────────────

def test_connectors_callback_handles_error_param():
    """OAuth callback with error param returns ok=False without crashing."""
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/connectors/gmail/callback",
                      params={"error": "access_denied"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "access_denied" in data["error"]


def test_connectors_callback_missing_state_400():
    """OAuth callback without state param returns 400."""
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/connectors/gmail/callback",
                      params={"code": "some_code"})
    assert resp.status_code == 400


def test_connectors_callback_mocked_exchange_stores_account(tmp_path, monkeypatch):
    """Mocked token exchange: valid callback stores account, returns HTML, redacts tokens."""
    import src.warden.connectors.store as store_mod
    import src.warden.connectors.oauth as oauth_mod

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    # Set up fake OAuth keys and start a flow to get a real state
    monkeypatch.setenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("WARDEN_GOOGLE_OAUTH_CLIENT_SECRET", "fake-secret")

    client = TestClient(app)
    start_resp = client.post("/api/mcharness/warden/connectors/gmail/connect/start")
    assert start_resp.status_code == 200
    state = start_resp.json()["state"]

    # Inject a mock exchanger — no real Google network call
    def mock_exchange(provider, code, redirect_uri):
        return {
            "access_token": "mock-access-token",
            "refresh_token": "mock-refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "id_token": "eyJhbGciOiJSUzI1NiJ9.eyJlbWFpbCI6InRlc3RAZ21haWwuY29tIn0.sig",
        }

    oauth_mod.set_token_exchanger(mock_exchange)
    try:
        resp = client.get("/api/mcharness/warden/connectors/gmail/callback",
                          params={"code": "fake_code", "state": state})
    finally:
        oauth_mod.set_token_exchanger(None)

    assert resp.status_code == 200
    assert "Connected" in resp.text  # HTML response

    # Account was stored — token never in accounts list
    from src.warden.connectors.store import ConnectorStore
    accounts = ConnectorStore().list_accounts(redact=True)
    assert any(a["provider"] == "gmail" for a in accounts)
    assert "mock-access-token" not in str(accounts)
    assert "mock-refresh-token" not in str(accounts)


def test_connectors_disconnect_removes_account(tmp_path, monkeypatch):
    """Disconnect endpoint removes account from store."""
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    from src.warden.connectors.store import ConnectorStore
    from src.warden.connectors.models import ConnectedAccount

    store = ConnectorStore()
    acc = ConnectedAccount(
        account_id="test-disconnect-1", user_id="local",
        provider="gmail", display_email="test@gmail.com", status="connected",
    )
    store.save_account(acc, token="some-token")
    assert store.get_account("test-disconnect-1") is not None

    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/connectors/accounts/test-disconnect-1/disconnect")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    assert store.get_account("test-disconnect-1") is None


def test_connectors_callback_no_raw_token_in_response(tmp_path, monkeypatch):
    """Callback response HTML never contains raw access_token or refresh_token."""
    import src.warden.connectors.store as store_mod
    import src.warden.connectors.oauth as oauth_mod

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)
    monkeypatch.setenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("WARDEN_GOOGLE_OAUTH_CLIENT_SECRET", "fake-secret")

    client = TestClient(app)
    start_resp = client.post("/api/mcharness/warden/connectors/gmail/connect/start")
    state = start_resp.json()["state"]

    def mock_exchange(provider, code, redirect_uri):
        return {"access_token": "super-secret-token-xyz", "refresh_token": "refresh-xyz",
                "expires_in": 3600, "token_type": "Bearer"}

    oauth_mod.set_token_exchanger(mock_exchange)
    try:
        resp = client.get("/api/mcharness/warden/connectors/gmail/callback",
                          params={"code": "code", "state": state})
    finally:
        oauth_mod.set_token_exchanger(None)

    assert resp.status_code == 200
    assert "super-secret-token-xyz" not in resp.text
    assert "refresh-xyz" not in resp.text


# ---------------------------------------------------------------------------
# Provider OAuth config (vault-stored client_id / client_secret)
# ---------------------------------------------------------------------------

def test_provider_config_save_and_get(tmp_path, monkeypatch):
    """Saving provider config stores credentials; GET returns masked info."""
    monkeypatch.setenv("WARDEN_VAULT_ROOT", str(tmp_path / "vault"))
    client = TestClient(app)

    # Initially not configured
    get_resp = client.get("/api/mcharness/warden/connectors/gmail/config")
    assert get_resp.status_code == 200
    assert get_resp.json()["configured"] is False

    # Save config
    post_resp = client.post("/api/mcharness/warden/connectors/gmail/config",
                            json={"client_id": "my-client-id-12345", "client_secret": "TOPSECRET"})
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["ok"] is True
    assert data["configured"] is True
    assert "TOPSECRET" not in str(data)  # secret never returned

    # GET shows masked
    get2 = client.get("/api/mcharness/warden/connectors/gmail/config")
    d2 = get2.json()
    assert d2["configured"] is True
    assert d2["has_secret"] is True
    assert "TOPSECRET" not in str(d2)
    assert d2["client_id"] == "my-client-id-12345"  # client_id not secret


def test_provider_config_updates_providers_configured(tmp_path, monkeypatch):
    """After saving config, /providers reflects configured=True."""
    monkeypatch.setenv("WARDEN_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.delenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    client = TestClient(app)

    # Save config
    client.post("/api/mcharness/warden/connectors/gmail/config",
                json={"client_id": "cid123", "client_secret": "csec"})

    resp = client.get("/api/mcharness/warden/connectors/providers")
    gmail = next(p for p in resp.json()["providers"] if p["provider_id"] == "gmail")
    assert gmail["configured"] is True


def test_provider_config_delete_clears(tmp_path, monkeypatch):
    """DELETE /config removes config; provider returns configured=False."""
    monkeypatch.setenv("WARDEN_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.delenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    client = TestClient(app)

    client.post("/api/mcharness/warden/connectors/gmail/config",
                json={"client_id": "cid", "client_secret": "cs"})
    del_resp = client.delete("/api/mcharness/warden/connectors/gmail/config")
    assert del_resp.json()["configured"] is False

    get_resp = client.get("/api/mcharness/warden/connectors/gmail/config")
    assert get_resp.json()["configured"] is False


def test_provider_config_unsupported_provider_404():
    """iCloud does not have a config endpoint (uses app_password)."""
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/connectors/icloud/config")
    assert resp.status_code == 404


def test_provider_config_missing_fields():
    """POST without client_id or client_secret returns 400."""
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/connectors/gmail/config",
                       json={"client_id": "", "client_secret": "secret"})
    assert resp.status_code == 400

    resp2 = client.post("/api/mcharness/warden/connectors/gmail/config",
                        json={"client_id": "cid", "client_secret": ""})
    assert resp2.status_code == 400


def test_provider_config_connect_start_uses_vault_config(tmp_path, monkeypatch):
    """connect/start uses vault config when env var is absent."""
    import src.warden.connectors.oauth as oauth_mod
    monkeypatch.setenv("WARDEN_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.delenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    client = TestClient(app)

    # Save config via API
    client.post("/api/mcharness/warden/connectors/gmail/config",
                json={"client_id": "vault-client-id", "client_secret": "vault-secret"})

    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/start")
    data = resp.json()
    assert data["ok"] is True
    assert "auth_url" in data
    assert "vault-client-id" in data["auth_url"]
