"""Integration tests for Warden MCP 2.0 Unified Architecture."""
from __future__ import annotations

from src.warden.mcp2_orchestrator import execute_unified_mcp2_lifecycle


def test_unified_mcp2_lifecycle_end_to_end():
    result = execute_unified_mcp2_lifecycle(
        user_request="Inspect current Warden project state and produce a concise architecture status report.",
        project="warden",
        required_capabilities=["software_architecture"],
    )

    assert result["ok"] is True
    assert result["context_revision"].startswith("ctx_")

    # Routing
    routing = result["routing"]
    assert routing["selected_agent"] in ("agy", "captain", "claude")

    # Run Envelope
    envelope = result["run_envelope"]
    assert envelope["final_status"] == "completed"
    assert len(envelope["tools_invoked"]) >= 2
    assert len(envelope["output_artifacts"]) >= 1

    # Artifact & Claim
    artifact = result["artifact"]
    assert artifact["uri"].startswith("warden://artifacts/art_")

    claim = result["claim"]
    assert claim["status"] == "verified"
    assert artifact["uri"] in claim["evidence_refs"]

    # AgentOps
    agentops = result["agentops"]
    assert agentops["passed"] == 7
    assert agentops["component_score"] == 1.0
