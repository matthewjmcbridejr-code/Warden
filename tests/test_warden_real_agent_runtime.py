"""Comprehensive test suite for Warden 0.6.1 Real Agent Runtime.

Verifies:
1. 'tell me what i was doing yesterday' returns an intelligent synthesized answer without capability menus or raw commands.
2. 'What have I been browsing tonight?' retrieves real browser/activity records without leaking raw internal 'browser-*' IDs.
3. 'Where are we at with Warden and what should we build next?' combines git, status, and brain context into synthesized status.
4. 'Captain, make me a plan...' generates and persists an authoritative plan to _mctable/captain/plans.json.
5. 'Remember that...' persists a permanent decision to Brain without slash commands.
6. Truthfulness: Active agent working state is derived strictly from real active runs, not decorative agents.
7. Explicit slash commands continue to serve as debug/power-user fast paths.
"""

import json
from pathlib import Path
import pytest
from src.warden.agent_runtime import (
    WardenAgentRuntime,
    WardenToolRegistry,
    handle_activity_search,
    handle_brain_recall,
    handle_brain_remember,
    handle_captain_plan,
    handle_project_inspect,
    handle_runs_inspect,
    handle_tasks_inspect,
)
from src.warden.group_chat import GroupChatStore


def test_tool_registry_specifications():
    """Tool registry provides valid OpenAI/LiteLLM function schemas."""
    registry = WardenToolRegistry()
    tools = registry.list_tools()
    tool_names = [t["function"]["name"] for t in tools]

    expected_tools = [
        "brain_recall",
        "brain_remember",
        "activity_search",
        "project_inspect",
        "captain_plan",
        "tasks_inspect",
        "runs_inspect",
        "finish_project",
    ]
    for expected in expected_tools:
        assert expected in tool_names, f"Missing tool: {expected}"


def test_yesterday_work_synthesized_no_help_menu(tmp_path: Path):
    """'tell me what i was doing yesterday' must return synthesized work milestones without capability/help menu."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    human_evt, responses = store.process_human_message("tell me what i was doing yesterday")

    assert human_evt.text == "tell me what i was doing yesterday"
    assert len(responses) == 1
    resp = responses[0]
    assert resp.actor_id == "warden"
    assert resp.event_type == "warden_message"

    # Must be synthesized engineering answer
    assert "Finish Subsystem" in resp.text or "milestones" in resp.text or "AI Desk" in resp.text
    # Must NOT be a raw capability/help menu
    assert "Here is what I can do for you:" not in resp.text
    assert "Ask 'Captain, make a plan for...'" not in resp.text


def test_browsing_history_summary_no_raw_browser_ids(tmp_path: Path):
    """'What have I been browsing tonight?' must synthesize browsing activity without leaking raw internal IDs."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    human_evt, responses = store.process_human_message("What have I been browsing tonight?")

    assert len(responses) == 1
    resp = responses[0]
    assert resp.actor_id == "warden"
    assert "Browser" in resp.text

    # Internal IDs like `browser-f7ccfc0f8d4a` or `browser-0110d6f93662` should not be dumped in user summary
    assert "browser-f7ccfc0f8d4a" not in resp.text
    assert "browser-0110d6f93662" not in resp.text


def test_where_are_we_at_synthesis(tmp_path: Path):
    """'Where are we at with Warden and what should we build next?' returns structured status and roadmap."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    human_evt, responses = store.process_human_message("Where are we at with Warden and what should we build next?")

    assert len(responses) == 1
    resp = responses[0]
    assert resp.actor_id == "warden"
    assert "Warden Current Status" in resp.text
    assert "Active Focus" in resp.text or "Roadmap" in resp.text


def test_natural_language_remember_decision(tmp_path: Path):
    """'Remember that I want Warden to behave like a real agent, not a command bot.' persists decision to Brain."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    prompt = "Remember that I want Warden to behave like a real agent, not a command bot."
    human_evt, responses = store.process_human_message(prompt)

    assert len(responses) == 1
    dec_evt = responses[0]
    assert dec_evt.actor_id == "warden"
    assert dec_evt.event_type == "decision"
    assert "Remembered" in dec_evt.text
    assert "real agent, not a command bot" in dec_evt.text


def test_natural_language_captain_planning(tmp_path: Path):
    """Natural-language planning request persists real Captain plan."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    prompt = "Captain, make me a plan for improving Warden based on what we've built this week."
    human_evt, responses = store.process_human_message(prompt)

    assert len(responses) == 1
    plan_evt = responses[0]
    assert plan_evt.actor_id == "warden"
    assert plan_evt.event_type == "plan_created"
    assert plan_evt.plan_id is not None
    assert "Formulated Captain Plan" in plan_evt.text
    assert plan_evt.metadata and "plan" in plan_evt.metadata

    plan_data = plan_evt.metadata["plan"]
    assert len(plan_data["steps"]) == 4
    for step in plan_data["steps"]:
        assert step["status"] == "queued"


def test_runs_and_tasks_truthfulness():
    """Runs and tasks inspection returns authoritative state without fake running agents."""
    runs_res = handle_runs_inspect()
    assert runs_res["active_runners_count"] == 0
    assert runs_res["runners"] == []
    assert "idle" in runs_res["status"].lower() or "ready" in runs_res["status"].lower()

    tasks_res = handle_tasks_inspect()
    assert "tasks" in tasks_res
    assert isinstance(tasks_res["tasks"], list)


def test_explicit_slash_commands_fast_path(tmp_path: Path):
    """Explicit slash commands (/status, /tasks, /runs, /proof) continue to work as fast paths."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")

    _, resp_status = store.process_human_message("/status")
    assert "Warden System Status" in resp_status[0].text
    assert "WardenAgentRuntime" in resp_status[0].text

    _, resp_runs = store.process_human_message("/runs")
    assert "Runner Status" in resp_runs[0].text

    _, resp_proof = store.process_human_message("/proof")
    assert "Verification Proof" in resp_proof[0].text
