"""Warden v2.6 — measurable loop tests (check command, dispatch budget, blocker)."""

import shutil

import pytest
from fastapi.testclient import TestClient

from src.warden.captain_plans import get_plan_record, persist_plan, plans_index_path
from src.warden.graph import MCTABLE_ROOT
from src.server.api import app


@pytest.fixture(autouse=True)
def clean_plans():
    path = plans_index_path(MCTABLE_ROOT)
    backup = path.read_bytes() if path.exists() else None
    yield
    if backup is not None:
        path.write_bytes(backup)
    elif path.exists():
        path.unlink()


def _make_plan(**overrides):
    plan_data = {
        "title": "v2.6 loop test plan",
        "summary": "loop conditions",
        "steps": [
            {"title": "Step one", "prompt": "do the thing", "agent_id": "codex_cli"},
        ],
        **overrides,
    }
    return persist_plan(
        MCTABLE_ROOT,
        goal="v2.6 loop goal",
        repo_id="mcharness-public-export",
        plan_data=plan_data,
    )


def test_plan_persists_loop_condition_fields():
    plan = _make_plan(check_command="true", max_dispatches=3, scope_paths=["src/warden/api.py"])
    assert plan["check_command"] == "true"
    assert plan["max_dispatches"] == 3
    assert plan["dispatch_count"] == 0
    assert plan["scope_paths"] == ["src/warden/api.py"]
    assert plan["blocker"] is None


def test_dispatch_budget_halts_plan_with_blocker():
    plan = _make_plan(max_dispatches=2)
    plan_id = plan["plan_id"]
    step_id = plan["steps"][0]["step_id"]
    client = TestClient(app)

    # Attempts 1 and 2 consume the budget (runner unavailable → blocked runs).
    for _ in range(2):
        resp = client.post(f"/api/mcharness/captain/plans/{plan_id}/steps/{step_id}/dispatch")
        assert resp.status_code == 200, resp.text
        assert resp.json().get("budget_exceeded") is not True

    # Attempt 3 exceeds the budget: the plan halts with a blocker, no infinite loop.
    resp = client.post(f"/api/mcharness/captain/plans/{plan_id}/steps/{step_id}/dispatch")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["budget_exceeded"] is True and data["blocked"] is True

    record = get_plan_record(MCTABLE_ROOT, plan_id)
    assert record["status"] == "stopped"
    assert record["blocker"]["kind"] == "budget_exceeded"
    assert "budget" in record["blocker"]["reason"].lower()

    # A stopped plan cannot be dispatched again — halted means halted.
    resp = client.post(f"/api/mcharness/captain/plans/{plan_id}/steps/{step_id}/dispatch")
    assert resp.status_code in (409, 200)
    if resp.status_code == 200:
        assert resp.json().get("dispatch") in ({}, None)


@pytest.fixture()
def allow_run_history_writes(monkeypatch):
    """Enable the step-complete route's write gate without enabling the real
    runner (dispatch stays on the blocked path)."""
    import src.warden.api as api_mod
    monkeypatch.setattr(api_mod, "_run_history_write_enabled", lambda: True)


def test_failing_check_command_blocks_completion(allow_run_history_writes):
    plan = _make_plan(check_command="false")
    plan_id = plan["plan_id"]
    step_id = plan["steps"][0]["step_id"]
    client = TestClient(app)
    resp = client.post(
        f"/api/mcharness/captain/plans/{plan_id}/steps/{step_id}/complete",
        json={"evidence_ids": []},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["check_command"] == "false"
    record = get_plan_record(MCTABLE_ROOT, plan_id)
    step = record["steps"][0]
    assert step["status"] == "needs_review"


def test_passing_check_command_allows_completion(allow_run_history_writes):
    plan = _make_plan(check_command="true")
    plan_id = plan["plan_id"]
    step_id = plan["steps"][0]["step_id"]
    client = TestClient(app)
    resp = client.post(
        f"/api/mcharness/captain/plans/{plan_id}/steps/{step_id}/complete",
        json={"evidence_ids": []},
    )
    assert resp.status_code == 200, resp.text
    record = get_plan_record(MCTABLE_ROOT, plan_id)
    assert record["steps"][0]["status"] == "passed"
    assert record["status"] == "completed"


def test_scope_paths_ride_on_dispatch_prompt():
    plan = _make_plan(scope_paths=["src/warden/agent_dispatcher.py", "tests/"])
    plan_id = plan["plan_id"]
    step_id = plan["steps"][0]["step_id"]
    client = TestClient(app)
    resp = client.post(f"/api/mcharness/captain/plans/{plan_id}/steps/{step_id}/dispatch")
    assert resp.status_code == 200
    # Runner is off in tests → blocked run records the prompt with scope line.
    from src.warden.run_history import get_run_record
    run_id = resp.json()["run_id"]
    run = get_run_record(MCTABLE_ROOT, run_id)
    assert run and "Allowed files/areas for this plan" in (run.get("prompt") or "")
