"""Unit tests for Reproducible Run Envelopes."""
from __future__ import annotations

import json
from src.warden.run_envelope import (
    RunEnvelope,
    finalize_run_envelope,
    get_run_envelope,
    open_run_envelope,
    record_tool_invocation,
)


def test_open_and_finalize_run_envelope():
    env = open_run_envelope(
        objective="Inspect Warden MCP 2.0 readiness",
        project="warden",
        agent_id="captain",
        protocol="a2a",
        provider_requested="VertexGeminiInferenceProvider",
        model="gemini-2.5-flash",
        context_revision="ctx_a1b2c3d4",
        tool_catalog_revision="cat_rev_e5f6",
        execution_budget={"max_tool_calls": 10},
    )

    assert isinstance(env, RunEnvelope)
    assert env.run_id.startswith("run_")
    assert env.final_status == "running"
    assert env.context_revision == "ctx_a1b2c3d4"
    assert env.model == "gemini-2.5-flash"

    # Record tool calls
    record_tool_invocation(env.run_id, "warden_bootstrap", status="success", duration_ms=45.0)
    record_tool_invocation(env.run_id, "warden_context_delta", status="success", duration_ms=12.0)

    # Finalize envelope
    finalized = finalize_run_envelope(
        env.run_id,
        status="completed",
        output_artifacts=["warden://artifacts/art_123456"],
        proof_ids=["m-proof-1"],
    )

    assert finalized is not None
    assert finalized.final_status == "completed"
    assert len(finalized.tools_invoked) == 2
    assert finalized.output_artifacts == ["warden://artifacts/art_123456"]
    assert finalized.ended_at is not None


def test_run_envelope_secret_sanitization():
    env = open_run_envelope(objective="Test secrets protection")
    finalized = finalize_run_envelope(env.run_id, status="completed")

    # Serialize envelope and verify secret absence
    json_str = finalized.model_dump_json().lower()
    assert "sk-or-" not in json_str
    assert "bearer " not in json_str
    assert "private_key" not in json_str
