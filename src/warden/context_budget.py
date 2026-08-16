"""Context Budget enforcement for Warden MCP 2.0.

Provides configurable memory, payload, and response byte caps to prevent giant
inline responses from overwhelming model context windows.
"""

from __future__ import annotations

import json
from typing import Any
from pydantic import BaseModel, Field

from src.warden.artifacts_protocol import ArtifactType, format_artifact_response, store_artifact


class ContextBudget(BaseModel):
    bootstrap_max_bytes: int = 2500
    delta_max_bytes: int = 1500
    retrieved_memories_max: int = 3
    retrieved_docs_max: int = 3
    inline_artifact_max_bytes: int = 4000
    inline_tool_result_max_bytes: int = 8000
    context_pack_max_bytes: int = 5000


_DEFAULT_CONTEXT_BUDGET = ContextBudget()


def get_default_context_budget() -> ContextBudget:
    """Returns global default ContextBudget parameters."""
    return _DEFAULT_CONTEXT_BUDGET


def enforce_result_budget(
    summary: str,
    payload: Any,
    *,
    type: ArtifactType = "agent_result",
    project: str = "warden",
    budget: ContextBudget | None = None,
) -> dict[str, Any]:
    """Enforces response budget caps, converting oversized outputs into ArtifactRefs."""
    eff_budget = budget or _DEFAULT_CONTEXT_BUDGET
    raw_json = json.dumps(payload) if not isinstance(payload, str) else payload

    if len(raw_json.encode("utf-8")) <= eff_budget.inline_tool_result_max_bytes:
        return {
            "summary": summary,
            "inline": True,
            "result": payload if not isinstance(payload, str) else json.loads(payload) if payload.startswith("{") else payload,
        }

    # Payload exceeds inline result limit — store as ArtifactRef
    artifact_ref = store_artifact(
        content=raw_json,
        type=type,
        mime_type="application/json" if not isinstance(payload, str) else "text/plain",
        project=project,
    )

    return format_artifact_response(
        summary=f"{summary} (Output stored as artifact {artifact_ref.artifact_id})",
        artifacts=[artifact_ref],
    )
