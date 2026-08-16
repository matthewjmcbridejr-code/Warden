"""Unit tests for Warden MCP 2.0 A2A Interoperability and Agent Matching."""
from __future__ import annotations

import json
from src.warden.agent_registry import (
    NormalizedAgentDescriptor,
    get_warden_a2a_agent_card,
    match_agents,
    normalize_agent_descriptor,
)


def test_warden_a2a_agent_card_structure():
    card = get_warden_a2a_agent_card("http://127.0.0.1:6969")
    assert card["name"] == "Warden Captain Orchestrator"
    assert card["protocol"] == "a2a"
    assert "capabilities" in card
    assert "software_architecture" in card["capabilities"]
    assert card["endpoint"] == "http://127.0.0.1:6969/api/mcharness/a2a/tasks"


def test_normalize_remote_a2a_agent_card():
    raw_card = {
        "name": "Remote Architect Agent",
        "description": "External agent capable of heavy architectural reviews",
        "protocol": "a2a",
        "capabilities": ["repository.read", "large_context", "software_architecture"],
        "accepted_task_types": ["software_architecture", "audit"],
        "endpoint": "https://agent.example.com/a2a/tasks",
        "provider": "Partner Labs",
        "cost_class": "medium",
    }

    norm = normalize_agent_descriptor(raw_card, source="a2a_discovery")
    assert isinstance(norm, NormalizedAgentDescriptor)
    assert norm.name == "Remote Architect Agent"
    assert "a2a" in norm.protocols
    assert norm.source == "a2a_discovery"
    assert norm.cost_class == "medium"
    assert "software_architecture" in norm.capabilities


def test_deterministic_capability_matching():
    agent_a = normalize_agent_descriptor({
        "id": "agent_code",
        "name": "Claude Coder",
        "capabilities": ["code.implementation", "unit_testing"],
        "accepted_task_types": ["code_implementation"],
        "cost_class": "low",
    })

    agent_b = normalize_agent_descriptor({
        "id": "agent_arch",
        "name": "AGY Architect",
        "capabilities": ["repository.read", "large_context", "software_architecture"],
        "accepted_task_types": ["software_architecture"],
        "cost_class": "medium",
    })

    descriptors = [agent_a, agent_b]

    # Task requires architecture
    results_arch = match_agents(
        descriptors,
        required_capabilities=["software_architecture", "repository.read"],
        task_type="software_architecture",
    )
    assert len(results_arch) == 2
    assert results_arch[0]["agent"]["agent_id"] == "agent_arch"
    assert results_arch[0]["match_score"] > results_arch[1]["match_score"]
    assert any("capability_match" in r for r in results_arch[0]["reason_codes"])

    # Task requires code implementation
    results_code = match_agents(
        descriptors,
        required_capabilities=["code.implementation"],
        task_type="code_implementation",
    )
    assert results_code[0]["agent"]["agent_id"] == "agent_code"
