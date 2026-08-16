"""Unit tests for Execution Budgets and Model Router."""
from __future__ import annotations

import time
from src.warden.execution_router import (
    ExecutionBudget,
    ModelRouter,
    RoutingDecision,
    get_budget_defaults,
)


def test_execution_budget_limits_and_exhaustion():
    budget = get_budget_defaults("tiny")
    assert budget.max_tool_calls == 5
    assert budget.max_inference_calls == 2

    # Not exceeded initially
    exceeded, reason = budget.check_exceeded()
    assert exceeded is False

    # Simulate tool calls exhaustion
    budget.tool_calls_used = 5
    exceeded, reason = budget.check_exceeded()
    assert exceeded is True
    assert "max_tool_calls" in reason


def test_model_router_decision_matrix():
    router = ModelRouter()

    # 1. Deterministic route (NO model used)
    r1 = router.route_task("Check git status and reconcile task health")
    assert r1.task_class == "DETERMINISTIC"
    assert r1.execution_mode == "local_logic"
    assert r1.model is None

    # 2. Code implementation route
    r2 = router.route_task("Implement new A2A feature in agent_registry.py", required_capabilities=["code.implementation"])
    assert r2.task_class == "CODE"
    assert r2.selected_agent == "claude"
    assert r2.model == "claude-3-5-sonnet"

    # 3. Deep architecture route
    r3 = router.route_task("Review multi-agent architecture across 200k tokens", required_capabilities=["software_architecture"])
    assert r3.task_class == "DEEP"
    assert r3.selected_agent == "agy"

    # 4. Balanced default route
    r4 = router.route_task("Evaluate general Captain ambiguity")
    assert r4.task_class == "BALANCED"
    assert r4.model == "gemini-2.5-flash"
    assert r4.provider == "VertexGeminiInferenceProvider"
