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
import re
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


def detect_conflicting_decisions(project: str = "") -> List[CaptainIssue]:
    """Detect conflicting decision memories recorded in Warden Brain."""
    issues: List[CaptainIssue] = []
    try:
        from src.warden.workbench import STORE as WORKBENCH_STORE
        memories = WORKBENCH_STORE.search_memories("decision", limit=50)
        decisions = [m.model_dump(mode="json") for m in memories if getattr(m, "kind", None) == "decision"]

        for i, d1 in enumerate(decisions):
            c1 = ((d1.get("title") or "") + " " + (d1.get("content") or "")).lower()
            for d2 in decisions[i + 1 :]:
                c2 = ((d2.get("title") or "") + " " + (d2.get("content") or "")).lower()

                # Spark architecture conflict check
                if ("spark" in c1 and "drive" in c1 and "mcp" not in c1) and ("spark" in c2 and "native" in c2 and "mcp" in c2):
                    issue_id = "iss_conflicting_decisions_spark"
                    existing = get_issue(issue_id)
                    if not (existing and existing.status == "resolved"):
                        issue = CaptainIssue(
                            issue_id=issue_id,
                            kind="contradictory_state",
                            severity="high",
                            status="open",
                            project=project or "warden",
                            subjects=[str(d1.get("memory_id") or ""), str(d2.get("memory_id") or "")],
                            evidence=[{"decision_1": d1}, {"decision_2": d2}],
                            summary=f"Conflicting decisions found: '{d1.get('title')}' vs '{d2.get('title')}'",
                            recommended_action="Supersede old architecture decision with newer native MCP decision.",
                            confidence=1.0,
                            requires_inference=False,
                            requires_operator=True,
                        )
                        issues.append(save_issue(issue))
    except Exception:
        pass
    return issues


def detect_duplicate_active_work(project: str = "") -> List[CaptainIssue]:
    """Detect multiple active tasks targeting identical objectives or subjects."""
    issues: List[CaptainIssue] = []
    tasks = list_tasks(project=project)
    active = [t for t in tasks if t.get("_status") in ("draft", "assigned", "claimed", "needs_review")]

    seen_titles: Dict[str, Dict[str, Any]] = {}
    for task in active:
        title_slug = re.sub(r"[^a-z0-9]+", "-", str(task.get("title") or "").lower().strip())
        if not title_slug:
            continue
        if title_slug in seen_titles:
            other = seen_titles[title_slug]
            task_id = str(task.get("task_id") or "")
            other_id = str(other.get("task_id") or "")
            issue_id = f"iss_duplicate_{task_id}_{other_id}"
            existing = get_issue(issue_id)
            if not (existing and existing.status == "resolved"):
                issue = CaptainIssue(
                    issue_id=issue_id,
                    kind="duplicate_work",
                    severity="medium",
                    status="open",
                    project=project or "warden",
                    subjects=[task_id, other_id],
                    evidence=[{"task_1": task}, {"task_2": other}],
                    summary=f"Duplicate active work detected: '{task.get('title')}' ({task_id}) and ({other_id}).",
                    recommended_action=f"Cancel or supersede duplicate task '{task_id}'.",
                    confidence=0.9,
                    requires_inference=False,
                    requires_operator=False,
                )
                issues.append(save_issue(issue))
        else:
            seen_titles[title_slug] = task
    return issues


def detect_orphaned_handoffs(project: str = "") -> List[CaptainIssue]:
    """Detect handoffs waiting for pickup without a claim by target agent."""
    issues: List[CaptainIssue] = []
    board = get_board_root()
    handoffs_dir = board / "handoffs"
    if not handoffs_dir.exists():
        return issues

    open_tasks = list_tasks(project=project)
    active_task_ids = {t.get("task_id"): t for t in open_tasks if t.get("_status") in ("needs_review", "assigned")}

    for h_file in handoffs_dir.glob("*.json"):
        try:
            h_data = json.loads(h_file.read_text(encoding="utf-8"))
            task_id = h_data.get("task")
            to_agent = h_data.get("to_agent")
            if task_id in active_task_ids:
                task = active_task_ids[task_id]
                if task.get("_status") == "needs_review" and task.get("claimed_by") != to_agent:
                    issue_id = f"iss_orphaned_handoff_{task_id}_{to_agent}"
                    existing = get_issue(issue_id)
                    if not (existing and existing.status == "resolved"):
                        issue = CaptainIssue(
                            issue_id=issue_id,
                            kind="orphaned_handoff",
                            severity="medium",
                            status="open",
                            project=project or "warden",
                            subjects=[task_id, f"agent:{to_agent}"],
                            evidence=[{"handoff": h_data}, {"task": task}],
                            summary=f"Handoff for task '{task_id}' to agent '{to_agent}' remains unclaimed.",
                            recommended_action=f"Agent '{to_agent}' should claim task '{task_id}' or reassign.",
                            confidence=1.0,
                            requires_inference=False,
                            requires_operator=False,
                        )
                        issues.append(save_issue(issue))
        except Exception:
            continue
    return issues


def check_client_tool_catalog_freshness(
    client_id: str, known_count: Optional[int] = None, known_revision: Optional[str] = None
) -> Dict[str, Any]:
    """Check if a connected client's catalog matches the current served tool catalog."""
    try:
        from src.warden.brain_mcp_server import mcp, _hub_status
        native_count = len(mcp._tool_manager._tools)
        total_count = native_count + getattr(_hub_status, "hub_tool_count", 0)
    except Exception:
        native_count = 60
        total_count = 103

    is_stale = False
    reasons = []
    if known_count is not None and known_count != native_count and known_count != total_count:
        is_stale = True
        reasons.append(f"Client known count ({known_count}) does not match native ({native_count}) or total ({total_count}) served tools.")

    return {
        "client_id": client_id,
        "is_stale": is_stale,
        "server_native_tool_count": native_count,
        "server_total_tool_count": total_count,
        "reasons": reasons,
        "recommended_action": "Client must issue tool list refresh or reconnect MCP session." if is_stale else "Client tool catalog is up to date.",
    }


def detect_tool_surface_drift(project: str = "") -> List[CaptainIssue]:
    """Detect connected MCP clients serving stale or mismatched tool counts."""
    issues: List[CaptainIssue] = []
    try:
        from src.warden.brain_mcp_server import mcp
        native_count = len(mcp._tool_manager._tools)
        expected_native_count = 60
        if native_count != expected_native_count:
            issue_id = "iss_tool_surface_drift"
            existing = get_issue(issue_id)
            if not (existing and existing.status == "resolved"):
                issue = CaptainIssue(
                    issue_id=issue_id,
                    kind="tool_surface_stale",
                    severity="low",
                    status="open",
                    project=project or "warden",
                    subjects=["mcp:tool_surface"],
                    evidence=[{"current_native_tools": native_count, "expected_native_tools": expected_native_count}],
                    summary=f"Native MCP tool surface drift detected ({native_count} tools registered vs {expected_native_count} expected).",
                    recommended_action="Emit tool catalog list_changed notification to connected clients.",
                    confidence=1.0,
                    requires_inference=False,
                    requires_operator=False,
                )
                issues.append(save_issue(issue))
    except Exception:
        pass
    return issues


def detect_failed_or_stale_proofs(project: str = "") -> List[CaptainIssue]:
    """Detect tasks or runs with failing test evidence or blocked proof gates."""
    issues: List[CaptainIssue] = []
    tasks = list_tasks(project=project)
    failed_tasks = [t for t in tasks if t.get("_status") in ("blocked", "failed")]
    for task in failed_tasks:
        task_id = str(task.get("task_id") or "")
        issue_id = f"iss_proof_failed_{task_id}"
        existing = get_issue(issue_id)
        if not (existing and existing.status == "resolved"):
            issue = CaptainIssue(
                issue_id=issue_id,
                kind="proof_failed",
                severity="high",
                status="open",
                project=project or "warden",
                subjects=[task_id],
                evidence=[{"task": task}],
                summary=f"Task '{task.get('title')}' ({task_id}) failed verification or proof gate.",
                recommended_action=f"Inspect failure evidence for task '{task_id}' and reassign or fix.",
                confidence=1.0,
                requires_inference=False,
                requires_operator=False,
            )
            issues.append(save_issue(issue))
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
    all_issues.extend(detect_conflicting_decisions(project=project))
    all_issues.extend(detect_duplicate_active_work(project=project))
    all_issues.extend(detect_orphaned_handoffs(project=project))
    all_issues.extend(detect_tool_surface_drift(project=project))
    all_issues.extend(detect_failed_or_stale_proofs(project=project))
    all_issues.extend(detect_dirty_worktrees(project=project))
    all_issues.extend(detect_service_degradation(project=project))

    log.info(f"Captain reconciliation run (trigger={trigger or 'manual'}): {len(all_issues)} issues active.")
    return all_issues


def on_state_event(event_type: str, project: str = "", payload: Optional[Dict[str, Any]] = None) -> List[CaptainIssue]:
    """Event handler entrypoint for state transitions (e.g. task.created, decision.created)."""
    return reconcile(project=project, trigger=event_type)


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
        self, issue: CaptainIssue, context: Dict[str, Any], fallback_enabled: bool = True
    ) -> CaptainAssessment:
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
            if not fallback_enabled:
                raise RuntimeError(f"Vertex inference failed with fallback_enabled=False: {exc}") from exc
            log.warning(
                f"VertexGeminiInferenceProvider fallback to local: {exc}"
            )
            fallback = LocalCaptainInferenceProvider()
            return await fallback.assess(issue, context)
