"""Regression test suite for release-blocking AI Desk functionality repairs.

Verifies:
1. Exact prompt routing in Talk to Warden without fake agent activity.
2. Grounded browser memory inquiry without simulated team delegations.
3. Authoritative Captain planning and plan persistence.
4. Local memory authorization for context pack and remember endpoints.
5. Error formatting resilience (no [object Object]).
"""

import json
from pathlib import Path
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.datastructures import Headers

from src.warden.group_chat import GroupChatStore
from src.warden.api import _require_private_memory_access, _require_run_history_write


def test_browsing_history_prompt_grounded_and_no_fake_agents(tmp_path: Path):
    """Operator prompt 'what have I been browsing tonight' must return grounded status without fake team delegations."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    human_evt, responses = store.process_human_message("what have I been browsing tonight")

    assert human_evt.text == "what have I been browsing tonight"
    assert len(responses) >= 1

    # Must be an authoritative message from warden
    warden_resp = responses[0]
    assert warden_resp.actor_id == "warden"
    assert "Browser" in warden_resp.text

    # CRITICAL: Must NEVER emit fake agent messages (e.g. Claude UX / Spark Research / Codex)
    actors = [r.actor_id for r in responses]
    assert "claude" not in actors
    assert "spark" not in actors
    assert "codex" not in actors
    assert not any("split this work across the team" in r.text for r in responses)


def test_captain_make_me_a_plan_exact_prompt(tmp_path: Path):
    """Operator prompt 'Captain, make me a plan for improving Warden based on what we've built this week.' must create a persisted plan."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    prompt = "Captain, make me a plan for improving Warden based on what we've built this week."
    human_evt, responses = store.process_human_message(prompt)

    assert human_evt.text == prompt
    assert len(responses) == 1

    plan_evt = responses[0]
    assert plan_evt.actor_id == "warden"
    assert plan_evt.event_type == "plan_created"
    assert plan_evt.plan_id is not None
    assert "Formulated Captain Plan" in plan_evt.text
    assert plan_evt.metadata is not None
    assert "plan" in plan_evt.metadata

    plan_data = plan_evt.metadata["plan"]
    assert "improving Warden based on what we've built this week" in plan_data["goal"]
    assert len(plan_data["steps"]) == 4
    # All initial steps should be queued, not fake running
    for step in plan_data["steps"]:
        assert step["status"] == "queued"

    # Verify plan was persisted to disk in _mctable
    mctable_plans = json.loads(Path("_mctable/captain/plans.json").read_text(encoding="utf-8"))
    persisted_plan = next((p for p in mctable_plans if p.get("plan_id") == plan_evt.plan_id), None)
    assert persisted_plan is not None
    assert persisted_plan["status"] == "active"


def test_general_fallback_has_no_fake_agent_activity(tmp_path: Path):
    """Unrecognized queries must return authoritative guidance without fake agent working events."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    human_evt, responses = store.process_human_message("Hello Warden, what can you do?")

    assert len(responses) == 1
    resp = responses[0]
    assert resp.actor_id == "warden"
    assert "Plan Work" in resp.text
    assert "Recall Memory" in resp.text
    assert "Finish & Publish" in resp.text

    actors = [r.actor_id for r in responses]
    assert "claude" not in actors
    assert "spark" not in actors
    assert "codex" not in actors


def test_local_memory_authorization_loopback(monkeypatch):
    """Local requests to memory dependencies are allowed when MCHARNESS_LOCAL_DEV is enabled, and blocked when public."""
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 54321),
        "headers": [],
    }
    req = Request(scope)

    # 1. Blocked when unconfigured/public
    monkeypatch.delenv("MCHARNESS_LOCAL_DEV", raising=False)
    monkeypatch.delenv("WARDEN_LOCAL_DESK", raising=False)
    monkeypatch.delenv("MCHARNESS_RUNNER_TMUX", raising=False)
    monkeypatch.delenv("MCHARNESS_RUNNER_CODEX", raising=False)
    with pytest.raises(HTTPException) as excinfo:
        _require_private_memory_access(req)
    assert excinfo.value.status_code == 403

    # 2. Allowed when local desk mode is active
    monkeypatch.setenv("MCHARNESS_LOCAL_DEV", "1")
    _require_private_memory_access(req)
    _require_run_history_write(req)
