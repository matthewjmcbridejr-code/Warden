"""Grounded Claims and Evidence module for Warden MCP 2.0.

Formalizes operational assertions supported by concrete system evidence refs
(service health, tasks, decisions, runs, proofs, artifacts, memory) rather than
unsupported model prose.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

ClaimType = Literal["epistemic", "task_ownership", "system_health", "architecture", "drift"]
ClaimStatus = Literal["active", "verified", "stale", "contradicted", "invalid"]
FreshnessLevel = Literal["live", "recent", "historical"]


class GroundedClaim(BaseModel):
    claim_id: str
    project: str = "warden"
    subject: str
    statement: str
    claim_type: ClaimType = "epistemic"
    status: ClaimStatus = "active"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    freshness: FreshnessLevel = "live"
    evidence_refs: list[str] = Field(default_factory=list)
    source_entities: list[str] = Field(default_factory=list)
    derived_from: str | None = None
    verification_method: str | None = None
    verified_at: str | None = None
    created_by: str = "warden"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# In-memory store for grounded claims with file backup in data root
_GROUNDED_CLAIMS: dict[str, GroundedClaim] = {}


def ground_claim(
    subject: str,
    statement: str,
    evidence_refs: list[str],
    *,
    project: str = "warden",
    claim_type: ClaimType = "epistemic",
    confidence: float = 1.0,
    created_by: str = "warden",
    derived_from: str | None = None,
) -> GroundedClaim:
    """Creates and records a grounded operational claim supported by system evidence URIs."""
    seed = f"{project}:{subject}:{statement}:{','.join(sorted(evidence_refs))}"
    claim_id = "clm_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]

    now_str = datetime.now(timezone.utc).isoformat()
    claim = GroundedClaim(
        claim_id=claim_id,
        project=project,
        subject=subject,
        statement=statement,
        claim_type=claim_type,
        status="verified" if confidence >= 0.9 and evidence_refs else "active",
        confidence=confidence,
        freshness="live",
        evidence_refs=evidence_refs,
        source_entities=evidence_refs,
        derived_from=derived_from,
        created_by=created_by,
        created_at=now_str,
        updated_at=now_str,
    )

    _GROUNDED_CLAIMS[claim_id] = claim
    return claim


def get_claim(claim_id: str) -> GroundedClaim | None:
    """Retrieves a grounded claim by ID."""
    return _GROUNDED_CLAIMS.get(claim_id)


def list_claims(project: str = "", status: str = "", claim_type: str = "") -> list[GroundedClaim]:
    """Lists grounded claims matching optional filters."""
    results = list(_GROUNDED_CLAIMS.values())
    if project:
        results = [c for c in results if c.project == project or c.project == "all"]
    if status:
        results = [c for c in results if c.status == status]
    if claim_type:
        results = [c for c in results if c.claim_type == claim_type]
    results.sort(key=lambda x: x.created_at, reverse=True)
    return results


def verify_claim(claim_id: str, *, verified: bool, method: str = "automated_check", note: str = "") -> GroundedClaim | None:
    """Updates verification status and timestamp of a grounded claim."""
    claim = _GROUNDED_CLAIMS.get(claim_id)
    if not claim:
        return None

    now_str = datetime.now(timezone.utc).isoformat()
    claim.status = "verified" if verified else "contradicted"
    claim.verification_method = method
    claim.verified_at = now_str
    claim.updated_at = now_str
    if not verified:
        claim.confidence = 0.0

    return claim
