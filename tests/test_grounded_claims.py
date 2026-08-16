"""Unit tests for Grounded Claims and Evidence."""
from __future__ import annotations

from src.warden.grounding import (
    GroundedClaim,
    get_claim,
    ground_claim,
    list_claims,
    verify_claim,
)


def test_ground_claim_creation():
    claim = ground_claim(
        subject="Gmail Service",
        statement="Gmail service is operational.",
        evidence_refs=["service://gmail/health"],
        project="warden",
        claim_type="system_health",
        confidence=1.0,
    )

    assert isinstance(claim, GroundedClaim)
    assert claim.claim_id.startswith("clm_")
    assert claim.status == "verified"
    assert claim.confidence == 1.0
    assert claim.evidence_refs == ["service://gmail/health"]


def test_get_and_list_claims():
    c1 = ground_claim(
        subject="Spark Adapter",
        statement="Spark Drive adapter is obsolete.",
        evidence_refs=["warden://decisions/m-spark-drive-1"],
        project="warden",
        claim_type="architecture",
    )

    c2 = ground_claim(
        subject="Agent Work",
        statement="Claude and AGY branch isolation verified.",
        evidence_refs=["warden://tasks/t123"],
        project="grademy",
        claim_type="task_ownership",
    )

    fetched = get_claim(c1.claim_id)
    assert fetched is not None
    assert fetched.subject == "Spark Adapter"

    warden_claims = list_claims(project="warden")
    assert any(c.claim_id == c1.claim_id for c in warden_claims)
    assert not any(c.claim_id == c2.claim_id for c in warden_claims)


def test_verify_claim():
    claim = ground_claim(
        subject="Build Verification",
        statement="Safe pytest suite passing.",
        evidence_refs=["warden://proofs/p905"],
        project="warden",
        confidence=0.8,
    )

    verified = verify_claim(claim.claim_id, verified=True, method="pytest_run")
    assert verified is not None
    assert verified.status == "verified"
    assert verified.verification_method == "pytest_run"

    failed = verify_claim(claim.claim_id, verified=False, method="pytest_run")
    assert failed.status == "contradicted"
    assert failed.confidence == 0.0
