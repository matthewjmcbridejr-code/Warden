"""Warden Action Model (WardenActionV1) for Warden Control Plane v1.

Represents a canonical, versioned envelope for consequential operations
prior to policy evaluation and execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field

ActionPhase = Literal["plan", "preflight", "pre_execute", "post_execute", "audit"]
ActionSource = Literal["mcp", "a2a", "captain", "runner", "rest", "cli", "github", "system"]
RiskClass = Literal[
    "READ",
    "LOW_WRITE",
    "EXTERNAL_WRITE",
    "DESTRUCTIVE",
    "CREDENTIAL",
    "DEPLOYMENT",
    "FINANCIAL",
    "SECURITY_SENSITIVE",
]


def redact_sensitive_arguments(args: dict[str, Any] | None) -> dict[str, Any]:
    """Redacts passwords, tokens, API keys, and sensitive environment variables."""
    if not args:
        return {}
    
    redacted = {}
    secret_patterns = re.compile(r"(key|token|password|secret|auth|bearer|cred)", re.IGNORECASE)

    for k, v in args.items():
        if secret_patterns.search(k):
            redacted[k] = "[REDACTED_SECRET]"
        elif isinstance(v, dict):
            redacted[k] = redact_sensitive_arguments(v)
        elif isinstance(v, list):
            redacted[k] = [
                redact_sensitive_arguments(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            redacted[k] = str(v)[:300]
    return redacted


def compute_argument_fingerprint(args: dict[str, Any] | None) -> str:
    """Computes a deterministic SHA-256 fingerprint of sanitized action arguments."""
    sanitized = redact_sensitive_arguments(args)
    payload = json.dumps(sanitized, sort_keys=True)
    return "fp_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class PrincipalIdentity(BaseModel):
    agent_id: str = "operator"
    session_id: str = "session_default"
    client_id: str | None = None
    user_id: str | None = None
    subject: str = "operator"
    transport_identity: str = "local"


class ActionTarget(BaseModel):
    kind: str = "tool"
    operation: str = "execute"
    tool_name: str | None = None


class ResourceRef(BaseModel):
    kind: str = "workspace"
    id: str = "warden"
    labels: dict[str, str] = Field(default_factory=dict)


class WorkspaceState(BaseModel):
    repo: str = "Warden"
    branch: str = "master"
    head_sha: str | None = None
    dirty: bool = False


class ActionProvenance(BaseModel):
    adapter: str = "mcp"
    adapter_version: str = "2.0.0"
    initiated_by: str = "agent"
    trusted_source: bool = True


class ActionRisk(BaseModel):
    risk_class: RiskClass = "LOW_WRITE"
    reason_codes: list[str] = Field(default_factory=list)


class WardenActionV1(BaseModel):
    schema_version: str = "1.0.0"
    action_id: str = Field(default_factory=lambda: f"act_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
    project: str = "warden"
    principal: PrincipalIdentity = Field(default_factory=PrincipalIdentity)
    source: ActionSource = "mcp"
    phase: ActionPhase = "pre_execute"
    task_id: str | None = None
    run_id: str | None = None
    action: ActionTarget = Field(default_factory=ActionTarget)
    resource: ResourceRef = Field(default_factory=ResourceRef)
    workspace: WorkspaceState = Field(default_factory=WorkspaceState)
    requested_capabilities: list[str] = Field(default_factory=list)
    context_revision: str | None = None
    tool_catalog_revision: str | None = None
    profile_revision: str | None = None
    provenance: ActionProvenance = Field(default_factory=ActionProvenance)
    risk: ActionRisk = Field(default_factory=ActionRisk)
    argument_fingerprint: str = ""
    safe_argument_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(
        cls,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        project: str = "warden",
        principal: PrincipalIdentity | None = None,
        source: ActionSource = "mcp",
        risk_class: RiskClass = "LOW_WRITE",
        task_id: str | None = None,
        run_id: str | None = None,
        requested_capabilities: list[str] | None = None,
    ) -> WardenActionV1:
        """Factory constructor ensuring secrets are redacted and fingerprints generated."""
        safe_summary = redact_sensitive_arguments(arguments)
        fingerprint = compute_argument_fingerprint(arguments)

        return cls(
            project=project,
            principal=principal or PrincipalIdentity(),
            source=source,
            action=ActionTarget(kind="tool", operation="call_tool", tool_name=tool_name),
            resource=ResourceRef(kind="tool", id=tool_name),
            task_id=task_id,
            run_id=run_id,
            requested_capabilities=requested_capabilities or [f"tool:{tool_name}"],
            risk=ActionRisk(risk_class=risk_class),
            argument_fingerprint=fingerprint,
            safe_argument_summary=safe_summary,
            evidence_refs=[f"warden://tools/{tool_name}"],
        )
