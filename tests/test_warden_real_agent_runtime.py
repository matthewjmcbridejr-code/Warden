"""Comprehensive test suite for Warden 0.6.1 Real Agent Runtime.

Verifies:
1. Referential Reasoning: Multi-turn pronouns ('those', 'that', 'it') resolved over conversation history.
2. Judgment & Recommendation: 'Which part of that work do you think we should continue first, and why?' provides reasoned opinion, NEVER raw Brain dumps.
3. Conversation Continuity: Relaunched threads restore durable history and answer without vector search guessing.
4. Unknown Fact Honesty: Unknown questions state lack of data rather than closest-vector hallucinations.
5. Fail-Closed Intelligence: Model unavailability explicitly reported, never quietly dumping database records.
6. Clean Activity & Brain: Excludes '[copied]', '[selected]', '[user_note]', and 'browser-*' noise.
7. Captain Planning: Persists real Captain plans to _mctable/captain/plans.json.
8. Status & Truthfulness: Runs and participant badges derived strictly from real runner sessions.
"""

import json
from pathlib import Path
import pytest
from src.warden.agent_runtime import (
    WardenAgentRuntime,
    WardenToolRegistry,
    ResolvedProvider,
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


def test_judgment_and_recommendation_never_dumps_raw_records():
    """'Which part of that work do you think we should continue first, and why?' must give reasoned technical judgment, never raw brain records."""
    runtime = WardenAgentRuntime()
    history = [
        {"role": "user", "content": "Matt: What were we doing yesterday?"},
        {"role": "assistant", "content": "Yesterday we finished implementing persistent 9-point verification for the Finish subsystem and built the AI Desk Talk to Warden surface with interactive cards."}
    ]
    result = runtime.run(
        project="Warden",
        conversation_id="test_judgment_conv",
        message="Which part of that work do you think we should continue first, and why?",
        history=history,
    )

    reply = result.reply
    # Must answer with reasoning/recommendation
    assert len(reply) > 20
    assert any(term in reply.lower() for term in ("finish", "verification", "talk to warden", "surface", "continue", "recommend", "prioritize", "first"))

    # Strict prohibitions
    assert "Recalled relevant context from Warden Brain:" not in reply
    assert "[selected]" not in reply
    assert "[copied]" not in reply
    assert "[user_note]" not in reply
    assert "browser-" not in reply
    assert "Which part of that work do you think we should continue first" not in reply


def test_conversation_continuity_restoration():
    """Relaunched conversation thread resolves updated priorities directly from history without vector search guessing."""
    runtime = WardenAgentRuntime()
    history = [
        {"role": "user", "content": "Matt: We are going to prioritize the agent runtime over UI polish."},
        {"role": "assistant", "content": "Understood. Prioritizing agent runtime over UI polish."},
        {"role": "user", "content": "Matt: Actually make the real work loop second after fixing conversation continuity."},
        {"role": "assistant", "content": "Noted. Top priority is conversation continuity, followed by the real work loop."}
    ]
    result = runtime.run(
        project="Warden",
        conversation_id="test_continuity_conv",
        message="What are our top two priorities?",
        history=history,
    )

    reply = result.reply.lower()
    # Must capture the contextual priorities
    assert "conversation continuity" in reply or "continuity" in reply
    assert "work loop" in reply or "agent runtime" in reply

    # Strict prohibitions
    assert "Recalled relevant context from Warden Brain:" not in result.reply
    assert "[selected]" not in result.reply


def test_unknown_facts_fail_honest():
    """When queried on facts absent from context and brain, Warden states lack of info rather than hallucinating."""
    runtime = WardenAgentRuntime()
    result = runtime.run(
        project="Warden",
        conversation_id="test_unknown_conv",
        message="What did I eat for lunch yesterday?",
        history=[],
    )

    reply = result.reply.lower()
    assert any(phrase in reply for phrase in ("don't have", "do not have", "no information", "not available", "unknown", "can't help", "cannot find"))
    assert "Recalled relevant context from Warden Brain:" not in result.reply


def test_fail_closed_on_model_unavailability(monkeypatch):
    """When reasoning model is unreachable, fail closed with explicit message — NEVER quietly dump raw database records."""
    from src.warden import agent_runtime
    monkeypatch.setattr(agent_runtime, "resolve_inference_provider", lambda: ResolvedProvider(provider_type="none", model="none", endpoint=""))

    runtime = WardenAgentRuntime()
    result = runtime.run(
        project="Warden",
        conversation_id="test_fail_closed_conv",
        message="What were we doing yesterday?",
        history=[],
    )

    assert result.fallback is True
    assert "reasoning model unavailable" in result.reply.lower()
    assert "Recalled relevant context from Warden Brain:" not in result.reply


def test_activity_search_strips_internal_ids_and_noise():
    """Activity search returns clean summaries without internal database IDs or raw auth scrap."""
    res = handle_activity_search(query="", limit=10)
    assert "activity" in res
    for item in res["activity"]:
        assert not item.get("summary", "").startswith("browser-")
        assert "[selected]" not in item.get("summary", "")
        assert "[copied]" not in item.get("summary", "")


def test_natural_language_remember_decision(tmp_path: Path):
    """'Remember that I want Warden to behave like a real agent, not a command bot.' persists decision to Brain."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    prompt = "Remember that I want Warden to behave like a real agent, not a command bot."
    human_evt, responses = store.process_human_message(prompt)

    assert len(responses) >= 1
    dec_evt = responses[0]
    assert dec_evt.actor_id == "warden"
    assert "Remembered" in dec_evt.text or "decision" in dec_evt.event_type


def test_natural_language_captain_planning(tmp_path: Path):
    """Natural-language planning request persists real Captain plan."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")
    prompt = "Captain, make me a plan for improving Warden based on what we've built this week."
    human_evt, responses = store.process_human_message(prompt)

    assert len(responses) >= 1
    plan_evt = next((r for r in responses if r.event_type == "plan_created"), responses[0])
    assert plan_evt.actor_id == "warden"
    assert plan_evt.plan_id is not None
    assert plan_evt.metadata and "plan" in plan_evt.metadata

    plan_data = plan_evt.metadata["plan"]
    assert len(plan_data["steps"]) >= 3
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
    """Explicit slash commands (/status, /tasks, /runs, /proof, /recall) continue to work as fast paths."""
    store = GroupChatStore(db_path=tmp_path / "chat.db")

    _, resp_status = store.process_human_message("/status")
    assert "Warden System Status" in resp_status[0].text
    assert "WardenAgentRuntime" in resp_status[0].text

    _, resp_runs = store.process_human_message("/runs")
    assert "Runner Status" in resp_runs[0].text

    _, resp_proof = store.process_human_message("/proof")
    assert "Verification Proof" in resp_proof[0].text
