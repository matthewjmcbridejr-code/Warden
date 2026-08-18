"""Unit and integration test suite for Warden Finish Subsystem."""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.warden.app import app
from src.warden.finish.models import (
    FinishJob,
    FinishStage,
    SecretRef,
    AcceptanceSpec,
    AcceptanceResult,
)
from src.warden.finish.store import FinishJobStore
from src.warden.finish.secret_vault import SecretVault
from src.warden.finish.control_plane_bridge import FinishControlPlaneBridge
from src.warden.finish.verifier import PlaywrightAcceptanceVerifier
from src.warden.finish.repair_loop import BoundedRepairEngine
from src.warden.finish.proof_pack import FinishProofPackGenerator
from src.warden.finish.pipeline import FinishPipeline
from src.warden.capability_grants import ControlPlaneStore
from src.warden.finish.adapters.vercel import VercelFinishAdapter
from src.warden.finish.adapters.supabase import SupabaseFinishAdapter


@pytest.fixture
def tmp_job_dir(tmp_path):
    return tmp_path / "jobs"


@pytest.fixture
def tmp_vault_dir(tmp_path):
    return tmp_path / "secrets"


@pytest.fixture
def store(tmp_job_dir):
    return FinishJobStore(root_dir=tmp_job_dir)


@pytest.fixture
def vault(tmp_vault_dir):
    return SecretVault(vault_dir=tmp_vault_dir)


def test_finish_job_models_and_store(store):
    job = FinishJob(
        job_id="job_test_101",
        project="TestApp",
        repo_path=str(Path.cwd()),
        objective="Deploy client portal app",
    )
    assert job.current_stage == FinishStage.INSPECT
    assert len(job.stage_history) == 0

    job.record_transition(FinishStage.PLAN, "Planning stage note")
    assert job.current_stage == FinishStage.PLAN
    assert len(job.stage_history) == 1

    saved = store.save(job)
    retrieved = store.get("job_test_101")
    assert retrieved is not None
    assert retrieved.job_id == "job_test_101"
    assert retrieved.current_stage == FinishStage.PLAN
    assert len(retrieved.stage_history) == 1


def test_secret_vault_and_redaction(vault):
    ref = vault.store_secret("ClientPortal", "DATABASE_URL", "postgresql://user:supersecretpass@db.example.com/prod", description="Prod DB")
    assert ref.key == "DATABASE_URL"
    assert ref.ref_uri == "secret://project/ClientPortal/database-url"

    resolved = vault.resolve_secret(ref.ref_uri)
    assert resolved == "postgresql://user:supersecretpass@db.example.com/prod"

    raw_text = "Connection string is postgresql://user:supersecretpass@db.example.com/prod for production."
    redacted = vault.redact_text(raw_text)
    assert "supersecretpass" not in redacted
    assert "[SECRET_REF: secret://project/ClientPortal/database-url]" in redacted


def test_control_plane_bridge(store, tmp_path):
    job = FinishJob(job_id="job_cp_1", project="Demo", repo_path=str(Path.cwd()), objective="Verify CP")
    cp_store = ControlPlaneStore(store_path=tmp_path / "cp_store.json")
    bridge = FinishControlPlaneBridge(store=cp_store)

    # Inspect action should be ALLOWED automatically
    decision_inspect, app_inspect = bridge.evaluate_action(job, "finish_inspect", {}, risk_class="READ")
    assert decision_inspect.verdict == "ALLOW"
    assert app_inspect is None

    # Promote production action should trigger ASK and create PENDING approval
    decision_promote, app_promote = bridge.evaluate_action(job, "finish_promote_production", {}, risk_class="DESTRUCTIVE")
    assert decision_promote.verdict == "ASK"
    assert app_promote is not None
    assert app_promote.status == "PENDING"
    assert len(job.approvals) == 1


def test_verifier_execution(tmp_path):
    verifier = PlaywrightAcceptanceVerifier(screenshot_dir=tmp_path / "screenshots")
    # Verify local server or mock target
    result = verifier.verify("job_v1", "http://127.0.0.1:6969", stage="VERIFY_PREVIEW")
    assert isinstance(result, AcceptanceResult)
    assert result.total_count >= 8
    assert result.passed_count > 0
    assert result.job_id == "job_v1"


def test_repair_loop(vault):
    job = FinishJob(job_id="job_repair_1", project="RepairDemo", repo_path=str(Path.cwd()), objective="Repair test")
    job.current_stage = FinishStage.VERIFY_PREVIEW
    repair_engine = BoundedRepairEngine(vault=vault)

    classified = repair_engine.classify_failure("VERIFY_PREVIEW", "Connection failed: DATABASE_URL missing")
    assert classified == "MISSING_DATABASE_URL"

    success, note = repair_engine.attempt_repair(job, "DATABASE_URL missing")
    assert success is True
    assert len(job.repair_attempts) == 1
    assert job.repair_attempts[0].issue_class == "MISSING_DATABASE_URL"
    assert len(job.secret_refs) > 0


def test_proof_pack_generator(tmp_path, vault):
    gen = FinishProofPackGenerator(output_dir=tmp_path / "proofs", vault=vault)
    job = FinishJob(
        job_id="job_proof_1",
        project="PortalApp",
        repo_path=str(Path.cwd()),
        objective="Ship PortalApp",
        preview_url="https://portal.vercel.app",
        production_url="https://portal.com",
    )
    job.latest_acceptance_result = AcceptanceResult(
        job_id="job_proof_1",
        target_url="https://portal.vercel.app",
        stage="VERIFY_PREVIEW",
        passed_count=9,
        total_count=9,
        passed=True,
    )
    proof_file = gen.generate_proof_pack(job)
    assert os.path.exists(proof_file)
    with open(proof_file, "r") as f:
        content = f.read()
    assert "9/9" in content
    assert "PortalApp" in content


def test_finish_pipeline_execution(store, vault, tmp_path):
    class MockVerifier:
        def verify(self, job_id, target_url, stage="VERIFY_PREVIEW", spec=None):
            return AcceptanceResult(
                job_id=job_id,
                target_url=target_url,
                stage=stage,
                passed_count=9,
                total_count=9,
                passed=True,
                summary="9/9 functional checks passed",
            )

    cp_store = ControlPlaneStore(store_path=tmp_path / "cp_pipe.json")
    bridge = FinishControlPlaneBridge(store=cp_store)
    pipeline = FinishPipeline(
        store=store,
        vault=vault,
        bridge=bridge,
        verifier=MockVerifier(),
        proof_gen=FinishProofPackGenerator(output_dir=tmp_path / "proofs", vault=vault),
    )
    job = FinishJob(job_id="job_pipe_1", project="PipeProject", repo_path=str(Path.cwd()), objective="Pipeline test")
    store.save(job)

    # Step 1: INSPECT -> PLAN
    job = pipeline.run_step("job_pipe_1")
    assert job.current_stage == FinishStage.PLAN

    # Step 2: PLAN -> BUILD
    job = pipeline.run_step("job_pipe_1")
    assert job.current_stage == FinishStage.BUILD

    # Step through pipeline until approval boundary (READY_TO_PUBLISH)
    for _ in range(10):
        if job.current_stage in (FinishStage.READY_TO_PUBLISH, FinishStage.COMPLETE, FinishStage.FAILED):
            break
        job = pipeline.run_step("job_pipe_1")

    assert job.current_stage == FinishStage.READY_TO_PUBLISH

    # Execute step on READY_TO_PUBLISH to evaluate publish approval action
    job = pipeline.run_step("job_pipe_1")
    assert len(job.approvals) == 1
    assert job.approvals[0].status == "PENDING"


def test_finish_api_endpoints(store):
    client = TestClient(app)

    # 1. Create job via API
    resp = client.post("/api/mcharness/finish/jobs", json={"project": "APIApp", "repo_path": ".", "objective": "API Test"})
    assert resp.status_code == 200
    data = resp.json()
    job_id = data["job_id"]
    assert data["project"] == "APIApp"

    # 2. Get job details
    resp_get = client.get(f"/api/mcharness/finish/jobs/{job_id}")
    assert resp_get.status_code == 200
    assert resp_get.json()["job_id"] == job_id

    # 3. List jobs
    resp_list = client.get("/api/mcharness/finish/jobs")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) >= 1
