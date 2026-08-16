"""Reproducible Run Envelope for Warden MCP 2.0.

Extends existing Warden run records with complete operational context metadata
for reproducibility without storing hidden model reasoning tokens or secrets.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class RunEnvelope(BaseModel):
    run_id: str
    task_id: str | None = None
    project: str = "warden"
    agent_id: str = "captain"
    agent_version: str | None = "2.0.0"
    protocol: str = "local" # local, mcp, a2a, external
    provider_requested: str | None = "VertexGeminiInferenceProvider"
    provider_used: str | None = "VertexGeminiInferenceProvider"
    model: str | None = "gemini-2.5-flash"
    fallback_used: bool = False
    operator_request: str | None = None
    objective: str = ""
    context_revision: str | None = None
    tool_catalog_revision: str | None = None
    decision_ids: list[str] = Field(default_factory=list)
    constraint_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    tools_invoked: list[dict[str, Any]] = Field(default_factory=list)
    input_artifacts: list[str] = Field(default_factory=list) # ArtifactRef URIs
    output_artifacts: list[str] = Field(default_factory=list) # ArtifactRef URIs
    start_branch: str | None = "master"
    start_sha: str | None = None
    end_branch: str | None = "master"
    end_sha: str | None = None
    tests: list[dict[str, Any]] = Field(default_factory=list)
    proof_ids: list[str] = Field(default_factory=list)
    eval_ids: list[str] = Field(default_factory=list)
    execution_budget: dict[str, Any] = Field(default_factory=dict)
    budget_usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    token_usage: dict[str, int] = Field(default_factory=dict)
    estimated_cost_usd: float | None = None
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ended_at: str | None = None
    final_status: str = "running" # running, completed, failed, cancelled, budget_exhausted


_RUN_ENVELOPES: dict[str, RunEnvelope] = {}


def open_run_envelope(
    objective: str,
    *,
    task_id: str | None = None,
    project: str = "warden",
    agent_id: str = "captain",
    protocol: str = "local",
    provider_requested: str | None = "VertexGeminiInferenceProvider",
    model: str | None = "gemini-2.5-flash",
    context_revision: str | None = None,
    tool_catalog_revision: str | None = None,
    operator_request: str | None = None,
    execution_budget: dict[str, Any] | None = None,
) -> RunEnvelope:
    """Opens a new reproducible RunEnvelope."""
    run_id = f"run_{int(time.time())}_{agent_id[:6]}"
    now_str = datetime.now(timezone.utc).isoformat()

    envelope = RunEnvelope(
        run_id=run_id,
        task_id=task_id,
        project=project,
        agent_id=agent_id,
        protocol=protocol,
        provider_requested=provider_requested,
        provider_used=provider_requested,
        model=model,
        operator_request=operator_request,
        objective=objective,
        context_revision=context_revision,
        tool_catalog_revision=tool_catalog_revision,
        execution_budget=execution_budget or {},
        started_at=now_str,
        final_status="running",
    )

    _RUN_ENVELOPES[run_id] = envelope
    return envelope


def record_tool_invocation(run_id: str, tool_name: str, status: str = "success", duration_ms: float = 0.0) -> None:
    """Appends safe tool invocation metadata to the run trajectory (NO secrets)."""
    env = _RUN_ENVELOPES.get(run_id)
    if not env:
        return

    env.tools_invoked.append({
        "name": tool_name,
        "status": status,
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def finalize_run_envelope(
    run_id: str,
    *,
    status: str = "completed",
    output_artifacts: list[str] | None = None,
    proof_ids: list[str] | None = None,
    end_sha: str | None = None,
) -> RunEnvelope | None:
    """Finalizes a run envelope with final status and artifacts."""
    env = _RUN_ENVELOPES.get(run_id)
    if not env:
        return None

    now_str = datetime.now(timezone.utc).isoformat()
    env.ended_at = now_str
    env.final_status = status
    if output_artifacts:
        env.output_artifacts.extend(output_artifacts)
    if proof_ids:
        env.proof_ids.extend(proof_ids)
    if end_sha:
        env.end_sha = end_sha

    # Verify NO secrets are leaked in envelope serialization
    env_json = env.model_dump_json().lower()
    for secret_pattern in ("sk-or-", "bearer ", "api_key=", "private_key=", "password="):
        if secret_pattern in env_json:
            raise ValueError(f"Run envelope serialization contained secret pattern '{secret_pattern}'!")

    return env


def get_run_envelope(run_id: str) -> RunEnvelope | None:
    """Retrieves a run envelope by ID."""
    return _RUN_ENVELOPES.get(run_id)
