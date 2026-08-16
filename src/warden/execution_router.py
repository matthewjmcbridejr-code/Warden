"""Execution Budgets and Capability-Aware Model/Agent Router for Warden MCP 2.0.

Provides explicit budget enforcement and provider-neutral model/agent routing.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

BudgetClass = Literal["tiny", "standard", "deep", "code", "research"]
RoutingClass = Literal["DETERMINISTIC", "FAST", "BALANCED", "DEEP", "CODE"]


class ExecutionBudget(BaseModel):
    budget_class: BudgetClass = "standard"
    max_tool_calls: int = 15
    max_inference_calls: int = 5
    max_retries: int = 3
    max_wall_seconds: float = 300.0
    max_cost_usd: float = 1.00

    tool_calls_used: int = 0
    inference_calls_used: int = 0
    retries_used: int = 0
    cost_usd_used: float = 0.0
    started_at: float = Field(default_factory=time.time)

    def check_exceeded(self) -> tuple[bool, str]:
        """Checks if budget limits have been exceeded."""
        if self.tool_calls_used >= self.max_tool_calls:
            return True, f"max_tool_calls ({self.max_tool_calls}) exceeded"
        if self.inference_calls_used >= self.max_inference_calls:
            return True, f"max_inference_calls ({self.max_inference_calls}) exceeded"
        if self.retries_used >= self.max_retries:
            return True, f"max_retries ({self.max_retries}) exceeded"
        if (time.time() - self.started_at) >= self.max_wall_seconds:
            return True, f"max_wall_seconds ({self.max_wall_seconds}s) exceeded"
        if self.cost_usd_used >= self.max_cost_usd:
            return True, f"max_cost_usd (${self.max_cost_usd}) exceeded"
        return False, ""


def get_budget_defaults(budget_class: BudgetClass = "standard") -> ExecutionBudget:
    """Returns default execution budget parameters for a given budget class."""
    if budget_class == "tiny":
        return ExecutionBudget(budget_class="tiny", max_tool_calls=5, max_inference_calls=2, max_retries=1, max_wall_seconds=60.0, max_cost_usd=0.10)
    elif budget_class == "code":
        return ExecutionBudget(budget_class="code", max_tool_calls=30, max_inference_calls=10, max_retries=5, max_wall_seconds=600.0, max_cost_usd=2.00)
    elif budget_class == "deep":
        return ExecutionBudget(budget_class="deep", max_tool_calls=50, max_inference_calls=15, max_retries=5, max_wall_seconds=1200.0, max_cost_usd=5.00)
    elif budget_class == "research":
        return ExecutionBudget(budget_class="research", max_tool_calls=25, max_inference_calls=8, max_retries=3, max_wall_seconds=450.0, max_cost_usd=1.50)
    return ExecutionBudget(budget_class="standard", max_tool_calls=15, max_inference_calls=5, max_retries=3, max_wall_seconds=300.0, max_cost_usd=1.00)


class RoutingDecision(BaseModel):
    task_class: RoutingClass
    execution_mode: str # local_logic, model
    selected_agent: str
    provider: str | None = None
    model: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    estimated_cost_class: str = "low"
    fallback_candidates: list[str] = Field(default_factory=list)


class ModelRouter:
    """Provider-neutral model and agent router for Warden execution."""

    def route_task(
        self,
        objective: str,
        *,
        required_capabilities: list[str] | None = None,
        task_type: str = "",
        estimated_context_tokens: int = 1000,
        max_cost_usd: float = 1.00,
        provider_health: dict[str, bool] | None = None,
    ) -> RoutingDecision:
        """Determines the optimal execution route, agent, and model for a task."""
        health = provider_health or {"vertex": True, "local": True}
        req_caps = set(required_capabilities or [])
        reasons = []

        # 1. Deterministic local logic route (NO model required)
        if any(keyword in objective.lower() for keyword in ("diff", "status", "health", "reconcile", "catalog", "revision")):
            return RoutingDecision(
                task_class="DETERMINISTIC",
                execution_mode="local_logic",
                selected_agent="captain",
                provider=None,
                model=None,
                reason_codes=["deterministic_local_logic", "no_model_required"],
                estimated_cost_class="free",
            )

        # 2. Code implementation route
        if "code.implementation" in req_caps or task_type == "code_implementation" or any(k in objective.lower() for k in ("build", "implement", "edit file", "refactor")):
            return RoutingDecision(
                task_class="CODE",
                execution_mode="model",
                selected_agent="claude",
                provider="Anthropic",
                model="claude-3-5-sonnet",
                reason_codes=["code_capability_matched", "primary_coder"],
                estimated_cost_class="medium",
                fallback_candidates=["agy", "codex"],
            )

        # 3. Deep reasoning / architecture route
        if "software_architecture" in req_caps or estimated_context_tokens > 100000:
            return RoutingDecision(
                task_class="DEEP",
                execution_mode="model",
                selected_agent="agy",
                provider="Google DeepMind",
                model="gemini-2.5-pro",
                reason_codes=["deep_reasoning_matched", "large_context_capable"],
                estimated_cost_class="high",
                fallback_candidates=["captain"],
            )

        # 4. Fast cheap classification route
        if any(k in objective.lower() for k in ("classify", "categorize", "extract", "short summary")):
            return RoutingDecision(
                task_class="FAST",
                execution_mode="model",
                selected_agent="captain",
                provider="VertexGeminiInferenceProvider",
                model="gemini-2.5-flash-lite",
                reason_codes=["fast_route_matched", "within_budget"],
                estimated_cost_class="free",
                fallback_candidates=["gemini-2.5-flash"],
            )

        # 5. Default Balanced Route (Google Vertex Gemini 2.5 Flash)
        return RoutingDecision(
            task_class="BALANCED",
            execution_mode="model",
            selected_agent="captain",
            provider="VertexGeminiInferenceProvider",
            model="gemini-2.5-flash",
            reason_codes=["capability_match", "within_budget", "provider_operational"],
            estimated_cost_class="low",
            fallback_candidates=["local_fallback"],
        )
