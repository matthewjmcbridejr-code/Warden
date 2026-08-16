"""Warden Captain Orchestrator v1.

Continuous orchestration and reconciliation control plane for Warden.
Provides deterministic reconciliation, persistent issue ledger, bounded planning,
event-driven triggers, tool catalog refresh metadata, compact bootstrap, and provider-neutral
inference abstractions (local fallback and Vertex Gemini adapter).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.warden.board import (
    cancel_task,
    find_task,
    get_board_root,
    list_tasks,
    revalidate_task_or_claim,
    supersede_task,
)
from src.warden.paths import data_root

log = logging.getLogger("warden.captain_orchestrator")

CAPTAIN_ISSUES_DIR = data_root() / "captain" / "issues"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _get_issues_dir() -> Path:
    env_board = os.getenv("WARDEN_BOARD_ROOT") or os.getenv("MCTABLE_BOARD_ROOT")
    if env_board:
        d = Path(env_board).expanduser().parent / "captain" / "issues"
    else:
        d = data_root() / "captain" / "issues"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Issue Ledger Domain Models
# ---------------------------------------------------------------------------

ISSUE_KINDS = (
    "superseded_task",
    "stale_claim",
    "contradictory_state",
    "duplicate_work",
    "orphaned_handoff",
    "service_degraded",
    "tool_surface_stale",
    "dirty_uncommitted_work",
    "proof_failed",
    "proof_stale",
)


class CaptainIssue(BaseModel):
    issue_id: str
    kind: str
    severity: str = "medium"  # low, medium, high, critical
    status: str = "open"  # open, in_progress, resolved, ignored
    project: str = "warden"
    detected_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    subjects: List[str] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str
    recommended_action: str
    confidence: float = 1.0
    requires_inference: bool = False
    requires_operator: bool = False
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None


class CaptainAssessment(BaseModel):
    classification: str
    severity: str = "medium"
    confidence: float = 1.0
    explanation: str
    recommended_action: str
    requires_operator: bool = False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_issue(issue: CaptainIssue) -> CaptainIssue:
    issues_dir = _get_issues_dir()
    issue.updated_at = _now()
    path = issues_dir / f"{issue.issue_id}.json"
    path.write_text(issue.model_dump_json(indent=2), encoding="utf-8")
    return issue


def get_issue(issue_id: str) -> Optional[CaptainIssue]:
    issues_dir = _get_issues_dir()
    path = issues_dir / f"{issue_id}.json"
    if not path.exists():
        return None
    try:
        return CaptainIssue.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_issues(
    project: str = "", status: str = "", kind: str = ""
) -> List[CaptainIssue]:
    issues_dir = _get_issues_dir()
    if not issues_dir.exists():
        return []

    issues: List[CaptainIssue] = []
    for path in sorted(issues_dir.glob("*.json")):
        try:
            issue = CaptainIssue.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if project and issue.project.lower() != project.strip().lower():
                continue
            if status and issue.status != status:
                continue
            if kind and issue.kind != kind:
                continue
            issues.append(issue)
        except Exception:
            continue
    return issues


def resolve_issue(
    issue_id: str, resolution: str, actor: str = ""
) -> Optional[CaptainIssue]:
    issue = get_issue(issue_id)
    if not issue:
        return None

    issue.status = "resolved"
    issue.resolution = f"{actor}: {resolution}" if actor else resolution
    issue.resolved_at = _now()
    return save_issue(issue)


# ---------------------------------------------------------------------------
# Deterministic Reconciliation Detectors
# ---------------------------------------------------------------------------

def detect_superseded_tasks(project: str = "") -> List[CaptainIssue]:
    """Detect active tasks that are superseded by newer architectural decisions."""
    issues: List[CaptainIssue] = []

    # 1. Inspect active board tasks
    tasks = list_tasks(project=project)
    active_tasks = [t for t in tasks if t.get("_status") in ("draft", "assigned", "claimed", "blocked", "needs_review")]

    # 2. Check Brain memories for decisions that supersede older decisions/tasks
    decisions: List[Dict[str, Any]] = []
    try:
        from src.warden.workbench import STORE as WORKBENCH_STORE
        memories = WORKBENCH_STORE.search_memories("decision", limit=50)
        for m in memories:
            if getattr(m, "kind", None) == "decision":
                decisions.append(m.model_dump(mode="json"))
    except Exception:
        pass

    # Check specifically for Spark decision contradiction:
    # "Spark integration uses native custom MCP, not Drive sync"
    spark_native_decision = None
    for d in decisions:
        content = (d.get("content") or "") + " " + (d.get("title") or "")
        if "spark" in content.lower() and "native" in content.lower() and "mcp" in content.lower():
            spark_native_decision = d
            break

    for task in active_tasks:
        task_id = str(task.get("task_id") or "")
        title = str(task.get("title") or "")
        desc = str(task.get("description") or "")
        combined = (title + " " + desc).lower()

        # Check Spark Drive vs Native MCP conflict
        if spark_native_decision and ("spark" in combined and "drive" in combined):
            issue_id = f"iss_superseded_{task_id}"
            existing = get_issue(issue_id)
            if existing and existing.status == "resolved":
                continue

            issue = CaptainIssue(
                issue_id=issue_id,
                kind="superseded_task",
                severity="high",
                status="open",
                project=task.get("project") or project or "warden",
                subjects=[task_id, f"task:{task_id}"],
                evidence=[
                    {
                        "type": "newer_decision",
                        "decision_id": spark_native_decision.get("id"),
                        "decision_title": spark_native_decision.get("title"),
                        "decision_content": spark_native_decision.get("content"),
                    },
                    {
                        "type": "contradictory_active_task",
                        "task_id": task_id,
                        "task_title": title,
                        "task_status": task.get("_status"),
                        "task_claimed_by": task.get("claimed_by"),
                    },
                ],
                summary=f"Task '{title}' ({task_id}) is superseded by newer decision: 'Spark integration uses native custom MCP, not Drive sync.'",
                recommended_action=f"warden_supersede_task(task_id='{task_id}', reason='Superseded by decision: Spark uses native custom MCP, not Drive sync.', superseded_by_decision='{spark_native_decision.get('id')}')",
                confidence=1.0,
                requires_inference=False,
                requires_operator=False,
            )
            issues.append(save_issue(issue))

    return issues


def detect_stale_claims(project: str = "") -> List[CaptainIssue]:
    """Detect claims whose task is no longer open or active."""
    issues: List[CaptainIssue] = []
    board = get_board_root()
    claims_dir = board / "claims"
    if not claims_dir.exists():
        return issues

    open_tasks = list_tasks(project=project)
    open_task_ids = {t.get("task_id") for t in open_tasks if t.get("_status") in ("draft", "assigned", "claimed", "blocked", "needs_review")}

    for claim_file in claims_dir.glob("*.json"):
        try:
            claim = json.loads(claim_file.read_text(encoding="utf-8"))
            task_id = claim.get("task")
            if not task_id:
                continue

            if task_id not in open_task_ids:
                issue_id = f"iss_stale_claim_{claim.get('agent')}_{task_id}"
                existing = get_issue(issue_id)
                if existing and existing.status == "resolved":
                    continue

                task_obj, _ = find_task(task_id)
                task_status = task_obj.get("status") if task_obj else "not_found"

                issue = CaptainIssue(
                    issue_id=issue_id,
                    kind="stale_claim",
                    severity="medium",
                    status="open",
                    project=project or "warden",
                    subjects=[task_id, f"claim:{claim_file.stem}"],
                    evidence=[
                        {"claim": claim},
                        {"task_id": task_id, "task_status": task_status},
                    ],
                    summary=f"Claim by agent '{claim.get('agent')}' on task '{task_id}' is stale because task is {task_status}.",
                    recommended_action=f"Reconcile stale claim for task {task_id}.",
                    confidence=1.0,
                    requires_inference=False,
                    requires_operator=False,
                )
                issues.append(save_issue(issue))
        except Exception:
            continue

    return issues


def detect_dirty_worktrees(project: str = "") -> List[CaptainIssue]:
    """Detect uncommitted changes in git repository."""
    issues: List[CaptainIssue] = []
    try:
        repo_root = data_root().parents[1] if (data_root().name == "mcharness-public-export") else Path.cwd()
        res = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            dirty_files = [line.strip() for line in res.stdout.strip().splitlines()]
            if len(dirty_files) > 0:
                issue_id = "iss_dirty_worktree_main"
                existing = get_issue(issue_id)
                if not (existing and existing.status == "resolved"):
                    issue = CaptainIssue(
                        issue_id=issue_id,
                        kind="dirty_uncommitted_work",
                        severity="low",
                        status="open",
                        project=project or "warden",
                        subjects=["git:worktree"],
                        evidence=[{"dirty_files_count": len(dirty_files), "sample": dirty_files[:10]}],
                        summary=f"Repository has {len(dirty_files)} uncommitted dirty files.",
                        recommended_action="Commit or preserve dirty changes before running automated refactors.",
                        confidence=1.0,
                        requires_inference=False,
                        requires_operator=False,
                    )
                    issues.append(save_issue(issue))
    except Exception:
        pass
    return issues


def detect_service_degradation(project: str = "") -> List[CaptainIssue]:
    """Detect degraded or unhealthy Warden background services."""
    issues: List[CaptainIssue] = []
    try:
        from src.warden.mail.health import check_all_mail_health
        health = check_all_mail_health()
        for svc, state in health.items():
            if isinstance(state, dict) and state.get("status") in ("degraded", "unhealthy", "error"):
                issue_id = f"iss_svc_degraded_{svc}"
                existing = get_issue(issue_id)
                if not (existing and existing.status == "resolved"):
                    issue = CaptainIssue(
                        issue_id=issue_id,
                        kind="service_degraded",
                        severity="medium",
                        status="open",
                        project=project or "warden",
                        subjects=[f"service:{svc}"],
                        evidence=[state],
                        summary=f"Service '{svc}' is in degraded state: {state.get('reason') or state.get('status')}",
                        recommended_action=f"Check service configuration and auth for '{svc}'.",
                        confidence=1.0,
                        requires_inference=False,
                        requires_operator=True,
                    )
                    issues.append(save_issue(issue))
    except Exception:
        pass
    return issues


# ---------------------------------------------------------------------------
# Unified Reconciler Engine
# ---------------------------------------------------------------------------

def reconcile(project: str = "", trigger: str = "") -> List[CaptainIssue]:
    """Run deterministic reconciliation to discover, update, and persist issues.

    Guarantees idempotency: repeated calls update evidence rather than creating
    duplicate unresolved issues.
    """
    all_issues: List[CaptainIssue] = []

    all_issues.extend(detect_superseded_tasks(project=project))
    all_issues.extend(detect_stale_claims(project=project))
    all_issues.extend(detect_dirty_worktrees(project=project))
    all_issues.extend(detect_service_degradation(project=project))

    log.info(f"Captain reconciliation run (trigger={trigger or 'manual'}): {len(all_issues)} issues active.")
    return all_issues


# ---------------------------------------------------------------------------
# Captain Provider-Neutral Inference Abstraction
# ---------------------------------------------------------------------------

class CaptainInferenceProvider(ABC):
    @abstractmethod
    async def assess(
        self, issue: CaptainIssue, context: Dict[str, Any]
    ) -> CaptainAssessment:
        pass


class LocalCaptainInferenceProvider(CaptainInferenceProvider):
    """Deterministic local fallback inference provider."""

    async def assess(
        self, issue: CaptainIssue, context: Dict[str, Any]
    ) -> CaptainAssessment:
        return CaptainAssessment(
            classification=issue.kind,
            severity=issue.severity,
            confidence=0.9,
            explanation=f"Local deterministic classification for {issue.summary}",
            recommended_action=issue.recommended_action,
            requires_operator=issue.requires_operator,
        )


class VertexGeminiInferenceProvider(CaptainInferenceProvider):
    """Google Cloud / Vertex Gemini inference provider using Application Default Credentials."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: str = "us-central1",
        model: str = "gemini-1.5-flash",
    ):
        self.project_id = (
            project_id
            or os.getenv("VERTEX_PROJECT_ID")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or "grademy-dev"
        )
        self.location = os.getenv("VERTEX_LOCATION", location)
        self.model = os.getenv("VERTEX_MODEL", model)

    async def assess(
        self, issue: CaptainIssue, context: Dict[str, Any]
    ) -> CaptainAssessment:
        # Fallback cleanly if google.auth or credentials not configured
        try:
            import google.auth
            from google.auth.transport.requests import Request

            credentials, project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            credentials.refresh(Request())
            access_token = credentials.token

            import urllib.request

            url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{self.model}:generateContent"

            prompt = (
                f"You are the Warden Captain Orchestrator AI assistant.\n"
                f"Analyze this issue and provide structured assessment:\n"
                f"Issue kind: {issue.kind}\nSummary: {issue.summary}\nEvidence: {json.dumps(issue.evidence)}\n"
                f"Context: {json.dumps(context)}\n\n"
                f"Respond ONLY with a JSON object containing keys:\n"
                f"classification, severity, confidence, explanation, recommended_action, requires_operator"
            )

            req_body = json.dumps(
                {
                    "contents": [
                        {"role": "user", "parts": [{"text": prompt}]}
                    ],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500},
                }
            ).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=req_body,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                parsed = json.loads(text)
                return CaptainAssessment.model_validate(parsed)

        except Exception as exc:
            log.warning(
                f"VertexGeminiInferenceProvider fallback to local: {exc}"
            )
            fallback = LocalCaptainInferenceProvider()
            return await fallback.assess(issue, context)
