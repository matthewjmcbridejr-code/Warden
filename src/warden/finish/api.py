"""FastAPI router for Warden Finish Subsystem."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from .models import FinishJob, FinishStage
from .store import FinishJobStore
from .pipeline import FinishPipeline
from .proof_pack import FinishProofPackGenerator


router = APIRouter(prefix="/finish", tags=["finish"])
store = FinishJobStore()
pipeline = FinishPipeline(store=store)


class CreateFinishJobRequest(BaseModel):
    project: str = "Warden"
    repo_path: str = "."
    objective: str = "Finish and ship the application with Vercel and Supabase"


class ApproveJobRequest(BaseModel):
    decision: str = "APPROVED"  # APPROVED or DENIED
    operator_id: str = "operator"


import time

@router.post("/jobs", response_model=FinishJob)
def create_finish_job(req: CreateFinishJobRequest) -> FinishJob:
    job_id = f"job_finish_{int(time.time() * 1000)}"
    repo_abs = str(Path(req.repo_path).resolve())
    job = FinishJob(
        job_id=job_id,
        project=req.project,
        repo_path=repo_abs,
        objective=req.objective,
    )
    store.save(job)
    # Execute initial step (INSPECT -> PLAN)
    job = pipeline.run_step(job_id)
    return job


@router.post("/jobs/{job_id}/resume", response_model=FinishJob)
def resume_finish_job(job_id: str) -> FinishJob:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    job.update_heartbeat("resumed_worker")
    store.save(job)
    return pipeline.run_step(job_id, worker_id="resumed_worker")


@router.get("/jobs", response_model=List[FinishJob])
def list_finish_jobs(project: Optional[str] = None) -> List[FinishJob]:
    return store.list(project=project)


@router.get("/jobs/{job_id}", response_model=FinishJob)
def get_finish_job(job_id: str) -> FinishJob:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job


@router.post("/jobs/{job_id}/step", response_model=FinishJob)
def run_finish_job_step(job_id: str) -> FinishJob:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return pipeline.run_step(job_id)


@router.post("/jobs/{job_id}/approve", response_model=FinishJob)
def approve_finish_job(job_id: str, req: ApproveJobRequest) -> FinishJob:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    pending_approvals = [a for a in job.approvals if a.status == "PENDING"]
    if not pending_approvals:
        raise HTTPException(status_code=400, detail="No pending approvals for this job.")

    for app in pending_approvals:
        app.status = req.decision
        app.granted_by = req.operator_id

    if req.decision == "APPROVED":
        job.record_transition(FinishStage.PROMOTE_PRODUCTION, f"Approved by {req.operator_id}")
        store.save(job)
        job = pipeline.run_step(job_id)
    else:
        job.record_transition(FinishStage.BLOCKED, f"Denied by {req.operator_id}")
        store.save(job)

    return job


@router.get("/jobs/{job_id}/proof")
def get_job_proof(job_id: str) -> Dict[str, Any]:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    proof_gen = FinishProofPackGenerator()
    proof_path = proof_gen.generate_proof_pack(job)
    with open(proof_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {"job_id": job_id, "proof_path": proof_path, "content": content}
