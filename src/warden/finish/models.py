"""Data models and state definitions for Warden Finish Subsystem."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FinishStage(str, Enum):
    INSPECT = "INSPECT"
    PLAN = "PLAN"
    BUILD = "BUILD"
    REPAIR_BUILD = "REPAIR_BUILD"
    PROVISION_AUTH = "PROVISION_AUTH"
    PROVISION_DATABASE = "PROVISION_DATABASE"
    PROVISION_STORAGE = "PROVISION_STORAGE"
    CONFIGURE_ENV = "CONFIGURE_ENV"
    DEPLOY_PREVIEW = "DEPLOY_PREVIEW"
    VERIFY_PREVIEW = "VERIFY_PREVIEW"
    REPAIR_RUNTIME = "REPAIR_RUNTIME"
    READY_TO_PUBLISH = "READY_TO_PUBLISH"
    PROMOTE_PRODUCTION = "PROMOTE_PRODUCTION"
    VERIFY_PRODUCTION = "VERIFY_PRODUCTION"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class SecretRef(BaseModel):
    key: str
    project_id: str
    ref_uri: str  # e.g., secret://project/my-app/database-url
    description: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(cls, project_id: str, key: str, description: Optional[str] = None) -> SecretRef:
        slug_key = key.lower().replace("_", "-")
        uri = f"secret://project/{project_id}/{slug_key}"
        return cls(key=key, project_id=project_id, ref_uri=uri, description=description)

    def redacted_representation(self) -> str:
        return f"[SECRET_REF: {self.ref_uri}]"


class CheckItem(BaseModel):
    name: str
    category: str  # e.g., page_load, auth, upload, console, network, mobile
    passed: bool
    details: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AcceptanceSpec(BaseModel):
    page_loads: bool = True
    signup_login: bool = True
    dashboard_render: bool = True
    upload_listing: bool = True
    project_status_visible: bool = True
    unauthorized_block: bool = True
    no_serious_console_errors: bool = True
    no_critical_failed_network_calls: bool = True
    mobile_usable: bool = True


class AcceptanceResult(BaseModel):
    job_id: str
    target_url: str
    stage: str
    passed_count: int = 0
    total_count: int = 0
    passed: bool = False
    checks: List[CheckItem] = Field(default_factory=list)
    summary: str = ""
    screenshot_paths: List[str] = Field(default_factory=list)
    console_errors: List[str] = Field(default_factory=list)
    network_failures: List[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StageTransition(BaseModel):
    from_stage: Optional[FinishStage]
    to_stage: FinishStage
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    note: str = ""


class ActionRecord(BaseModel):
    action_type: str
    risk_class: str
    decision: str  # PERMIT, ASK, DENY
    summary: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ApprovalRecord(BaseModel):
    approval_id: str
    title: str
    action_type: str
    status: str  # PENDING, APPROVED, DENIED
    detail: str = ""
    granted_by: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RepairAttempt(BaseModel):
    attempt_index: int
    stage: str
    issue_class: str
    diagnosis: str
    action_taken: str
    status: str  # SUCCESS, FAILED
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ResourceRef(BaseModel):
    provider: str  # e.g., vercel, supabase
    resource_type: str  # e.g., project, database, storage_bucket, preview_deployment
    resource_id: str
    name: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FinishJob(BaseModel):
    job_id: str
    project: str
    repo_path: str
    objective: str
    current_stage: FinishStage = FinishStage.INSPECT
    stage_history: List[StageTransition] = Field(default_factory=list)
    acceptance_spec: AcceptanceSpec = Field(default_factory=AcceptanceSpec)
    resources: List[ResourceRef] = Field(default_factory=list)
    secret_refs: List[SecretRef] = Field(default_factory=list)
    actions: List[ActionRecord] = Field(default_factory=list)
    approvals: List[ApprovalRecord] = Field(default_factory=list)
    repair_attempts: List[RepairAttempt] = Field(default_factory=list)
    max_repair_budget: int = 3
    preview_url: Optional[str] = None
    production_url: Optional[str] = None
    latest_acceptance_result: Optional[AcceptanceResult] = None
    proof_pack_path: Optional[str] = None
    failure_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    heartbeat_at: Optional[str] = None
    worker_id: Optional[str] = None
    stage_timeout_seconds: int = 60

    def record_transition(self, to_stage: FinishStage, note: str = "") -> None:
        transition = StageTransition(from_stage=self.current_stage, to_stage=to_stage, note=note)
        self.stage_history.append(transition)
        self.current_stage = to_stage
        now_str = datetime.now(timezone.utc).isoformat()
        self.updated_at = now_str
        self.heartbeat_at = now_str

    def update_heartbeat(self, worker_id: Optional[str] = None) -> None:
        self.heartbeat_at = datetime.now(timezone.utc).isoformat()
        if worker_id is not None:
            self.worker_id = worker_id

    def is_stale(self, threshold_seconds: Optional[int] = None) -> bool:
        if self.current_stage in (FinishStage.COMPLETE, FinishStage.FAILED, FinishStage.BLOCKED):
            return False
        ts_str = self.heartbeat_at or self.updated_at or self.created_at
        try:
            dt = datetime.fromisoformat(ts_str)
            now = datetime.now(timezone.utc)
            timeout = threshold_seconds or self.stage_timeout_seconds
            return (now - dt).total_seconds() > timeout
        except Exception:
            return False
