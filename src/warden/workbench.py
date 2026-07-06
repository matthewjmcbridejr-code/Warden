from __future__ import annotations

import os
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .contracts import EvidenceRecord as ThreadEvidenceRecord
from .contracts import HardGate, MinionTask, PromptQueueItem, ScopedCommitPlan

MCTABLE_ROOT = Path(os.getenv("MCHARNESS_DATA_ROOT", "_mctable"))
WORKBENCH_ROOT = MCTABLE_ROOT / "workbench"
FILE_LOCK = threading.Lock()

SAFE_SLUG = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"
MEMORY_KINDS = Literal[
    "fact",
    "decision",
    "failure",
    "blocked_attempt",
    "proof",
    "claim",
    "handoff",
    "constraint",
    "test_result",
    "agent_prompt",
    "agent_result",
    "user_note",
    "repo_context",
    "fragile_file",
    "acceptance_test",
]
MEMORY_STATUSES = Literal["active", "superseded", "stale", "forgotten"]
MAX_MEMORY_CONTENT_CHARS = 12_000
DEFAULT_CONTEXT_MAX_MEMORIES = 8
DEFAULT_CONTEXT_MAX_CHARS = 6_000

_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----.*?"
    r"-----END (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b("
    r"(?:OPENAI|ANTHROPIC|GEMINI|GOOGLE|GROQ|GITHUB|OPENROUTER|AWS|AZURE)[A-Z0-9_]*(?:KEY|TOKEN|SECRET)"
    r"|API_KEY|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|PASSWORD|PASSWD|COOKIE"
    r")\s*=\s*(?P<quote>['\"]?)[^\s'\"\r\n]+(?P=quote)"
)
_AUTH_HEADER_RE = re.compile(r"(?im)\b(Authorization\s*:\s*Bearer)\s+[^\s\r\n]+")
_PASSWORD_FIELD_RE = re.compile(
    r"(?im)\b(password|passwd|pwd|cookie|sessionid)\s*[:=]\s*(?P<quote>['\"]?)[^\s'\"\r\n]+(?P=quote)"
)
_TOKEN_RE = re.compile(
    r"\b(?:sk-(?:ant-|or-)?[A-Za-z0-9._-]{6,}|gsk_[A-Za-z0-9._-]{6,}|gh[pousr]_[A-Za-z0-9_]{6,})\b"
)


class WorkbenchError(ValueError):
    pass


class WorkbenchAgent(BaseModel):
    agent_id: str
    name: str
    role: str = "operator"
    status: Literal["active", "paused", "disabled"] = "active"
    safety_profile_id: str = "operator_local"
    allowed_threads: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WorkbenchThread(BaseModel):
    thread_id: str
    agent_id: Optional[str] = None
    title: str
    objective: str
    status: Literal["open", "paused", "blocked", "closed"] = "open"
    next_action: str = "inspect"
    prompt_queue: list[PromptQueueItem] = Field(default_factory=list)
    minion_tasks: list[MinionTask] = Field(default_factory=list)
    evidence_records: list[ThreadEvidenceRecord] = Field(default_factory=list)
    hard_gates: list[HardGate] = Field(default_factory=list)
    scoped_commit_plan: Optional[ScopedCommitPlan] = None
    planned_acceptance_commands: list[str] = Field(default_factory=list)
    recovery_hint: Optional[str] = None
    notes: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class WorkbenchMessage(BaseModel):
    message_id: str
    thread_id: str
    author: str
    kind: Literal["planning", "instruction", "note", "evidence", "system", "command_request"] = "note"
    content: str
    status: Literal["recorded", "blocked"] = "recorded"
    recovery_hint: Optional[str] = None
    created_at: datetime


class WorkbenchSkill(BaseModel):
    skill_id: str
    title: str
    description: str
    path: Optional[str] = None
    enabled: bool = True
    notes: Optional[str] = None
    # Playbook fields (v2.1) — optional with defaults so pre-v2 skill JSON loads unchanged.
    when_to_use: Optional[str] = None
    inspect_files: list[str] = Field(default_factory=list)
    commands_allowed: list[str] = Field(default_factory=list)
    commands_forbidden: list[str] = Field(default_factory=list)
    proof_format: Optional[str] = None
    acceptance_checks: list[str] = Field(default_factory=list)
    rollback_notes: Optional[str] = None
    report_template: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WorkbenchMemory(BaseModel):
    memory_id: str
    scope: str
    summary: str
    source: str
    title: Optional[str] = None
    source_ref: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    kind: MEMORY_KINDS = "user_note"
    status: MEMORY_STATUSES = "active"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    project_id: Optional[str] = None
    repo_path: Optional[str] = None
    branch: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    compacted: bool = False
    notes: Optional[str] = None
    # Capture fidelity (v2.4 / personal_ai_os_plan PR 3): bounded raw source content,
    # with an explicit flag so distillation can tell "nothing more" from "thrown away".
    raw_content: Optional[str] = None
    raw_content_truncated: bool = False
    created_at: datetime
    updated_at: datetime


class WorkbenchArtifact(BaseModel):
    artifact_id: str
    thread_id: Optional[str] = None
    kind: str
    title: str
    path: str
    summary: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WorkbenchTool(BaseModel):
    name: str
    category: str
    status: Literal["available", "disabled", "not_implemented"] = "available"
    summary: str
    local_only: bool = True
    fake_worker_only: bool = True
    real_agent_launch_disabled: bool = True
    arbitrary_command_execution_disabled: bool = True
    recovery_hint: Optional[str] = None


class SafetyProfile(BaseModel):
    profile_id: str
    title: str
    summary: str
    local_only: bool = True
    fake_worker_only: bool = True
    real_agent_launch_disabled: bool = True
    arbitrary_command_execution_disabled: bool = True
    mcp_local_only: bool = True
    shell_enabled: bool = False
    notes: Optional[str] = None


class WorkbenchAgentCreateRequest(BaseModel):
    agent_id: str = Field(pattern=SAFE_SLUG)
    name: str = Field(min_length=1)
    role: str = "operator"
    status: Literal["active", "paused", "disabled"] = "active"
    safety_profile_id: str = "operator_local"
    allowed_threads: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class WorkbenchThreadCreateRequest(BaseModel):
    thread_id: Optional[str] = Field(default=None, pattern=SAFE_SLUG)
    title: str = Field(min_length=1)
    objective: Optional[str] = None
    goal: Optional[str] = None
    agent_id: Optional[str] = None
    status: Literal["open", "paused", "blocked", "closed"] = "open"
    next_action: str = "inspect"
    prompt_queue: list[PromptQueueItem] = Field(default_factory=list)
    minion_tasks: list[MinionTask] = Field(default_factory=list)
    evidence_records: list[ThreadEvidenceRecord] = Field(default_factory=list)
    hard_gates: list[HardGate] = Field(default_factory=list)
    scoped_commit_plan: Optional[ScopedCommitPlan] = None
    planned_acceptance_commands: list[str] = Field(default_factory=list)
    recovery_hint: Optional[str] = None
    notes: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkbenchThreadUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    objective: Optional[str] = Field(default=None, min_length=1)
    status: Optional[Literal["open", "paused", "blocked", "closed"]] = None
    next_action: Optional[str] = Field(default=None, min_length=1)
    recovery_hint: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class WorkbenchMessageCreateRequest(BaseModel):
    message_id: Optional[str] = Field(default=None, pattern=SAFE_SLUG)
    author: Optional[str] = Field(default=None, min_length=1)
    role: Optional[str] = Field(default=None, min_length=1)
    kind: Literal["instruction", "planning", "note", "evidence", "system", "command_request"] = "note"
    content: str = Field(min_length=1)


class WorkbenchSkillCreateRequest(BaseModel):
    skill_id: str = Field(pattern=SAFE_SLUG)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    path: Optional[str] = None
    enabled: bool = True
    notes: Optional[str] = None
    when_to_use: Optional[str] = None
    inspect_files: list[str] = Field(default_factory=list)
    commands_allowed: list[str] = Field(default_factory=list)
    commands_forbidden: list[str] = Field(default_factory=list)
    proof_format: Optional[str] = None
    acceptance_checks: list[str] = Field(default_factory=list)
    rollback_notes: Optional[str] = None
    report_template: Optional[str] = None


class WorkbenchMemoryCreateRequest(BaseModel):
    memory_id: Optional[str] = Field(default=None, pattern=SAFE_SLUG)
    scope: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source: str = Field(min_length=1)
    title: Optional[str] = None
    source_ref: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    kind: MEMORY_KINDS = "user_note"
    status: MEMORY_STATUSES = "active"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    project_id: Optional[str] = None
    repo_path: Optional[str] = None
    branch: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    compacted: bool = False
    notes: Optional[str] = None
    raw_content: Optional[str] = None
    raw_content_truncated: bool = False


class WorkbenchMemoryRememberRequest(BaseModel):
    memory_id: Optional[str] = Field(default=None, pattern=SAFE_SLUG)
    scope: str = Field(default="warden", min_length=1)
    content: str = Field(min_length=1)
    source: str = Field(default="warden")
    title: Optional[str] = None
    source_ref: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    kind: MEMORY_KINDS = "user_note"
    status: MEMORY_STATUSES = "active"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    project_id: Optional[str] = None
    repo_path: Optional[str] = None
    branch: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    compacted: bool = False
    notes: Optional[str] = None


class WorkbenchArtifactCreateRequest(BaseModel):
    artifact_id: str = Field(pattern=SAFE_SLUG)
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    path: str = Field(min_length=1)
    thread_id: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None


class WorkbenchRunProofGateCreateRequest(BaseModel):
    gate_id: Optional[str] = Field(default=None, pattern=SAFE_SLUG)
    title: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    requires_human: bool = True
    kind: Optional[str] = Field(default=None, min_length=1)
    triggered_by: Optional[str] = Field(default=None, min_length=1)


class WorkbenchRunProofGateDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "edit_requested"]
    actor: str = Field(min_length=1)
    note: Optional[str] = None


class WorkbenchCaptainRunCreateRequest(BaseModel):
    objective: str = Field(min_length=1)


class WorkbenchRunEvent(BaseModel):
    event_id: str
    run_id: str
    thread_id: str
    event_type: Literal[
        "instruction",
        "plan",
        "minion_assignment",
        "tool_result",
        "evidence",
        "proof_gate",
        "approval",
        "blocked",
        "artifact",
        "note",
    ]
    title: str
    detail: str
    severity: Literal["info", "success", "warning", "blocked", "error"] = "info"
    created_at: datetime


class EvidenceRecord(BaseModel):
    evidence_id: str
    run_id: str
    thread_id: str
    title: str
    summary: str
    source_type: Literal["test", "log", "manual", "artifact", "api", "screenshot", "verifier"]
    source_ref: Optional[str] = None
    verdict: Literal["unknown", "passed", "failed", "blocked"] = "unknown"
    created_at: datetime


class ProofGate(BaseModel):
    gate_id: str
    run_id: str
    thread_id: str
    title: str
    reason: str
    status: Literal["open", "approved", "rejected", "blocked"] = "open"
    requires_human: bool = True
    created_at: datetime
    decided_at: Optional[datetime] = None
    decision_id: Optional[str] = None


class ApprovalDecision(BaseModel):
    decision_id: str
    gate_id: str
    run_id: str
    thread_id: str
    actor: str
    decision: Literal["approved", "rejected", "edit_requested"]
    note: Optional[str] = None
    created_at: datetime


class WorkbenchRun(BaseModel):
    run_id: str
    thread_id: str
    title: str
    status: Literal["queued", "running", "paused", "blocked", "completed", "failed", "cancelled"] = "queued"
    current_step: str
    created_at: datetime
    updated_at: datetime
    recovery_hint: Optional[str] = None
    events: list[WorkbenchRunEvent] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    proof_gates: list[ProofGate] = Field(default_factory=list)
    approval_decisions: list[ApprovalDecision] = Field(default_factory=list)


class WorkbenchRunCreateRequest(BaseModel):
    run_id: Optional[str] = Field(default=None, pattern=SAFE_SLUG)
    title: str = Field(min_length=1)
    current_step: str = Field(min_length=1)
    status: Literal["queued", "running", "paused", "blocked", "completed", "failed", "cancelled"] = "queued"
    recovery_hint: Optional[str] = None


class WorkbenchRunEventCreateRequest(BaseModel):
    event_id: Optional[str] = Field(default=None, pattern=SAFE_SLUG)
    event_type: Literal[
        "instruction",
        "plan",
        "minion_assignment",
        "tool_result",
        "evidence",
        "proof_gate",
        "approval",
        "blocked",
        "artifact",
        "note",
    ]
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    severity: Literal["info", "success", "warning", "blocked", "error"] = "info"


class WorkbenchEvidenceRecordCreateRequest(BaseModel):
    evidence_id: Optional[str] = Field(default=None, pattern=SAFE_SLUG)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_type: Literal["test", "log", "manual", "artifact", "api", "screenshot", "verifier"]
    source_ref: Optional[str] = None
    verdict: Literal["unknown", "passed", "failed", "blocked"] = "unknown"


class WorkbenchProofGateCreateRequest(BaseModel):
    gate_id: Optional[str] = Field(default=None, pattern=SAFE_SLUG)
    kind: str = Field(default="manual_review", min_length=1)
    reason: str = Field(min_length=1)
    triggered_by: str = Field(default="operator", min_length=1)
    requires_human: bool = True
    title: Optional[str] = None


class WorkbenchProofGateDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "edit_state"]
    actor: str = Field(min_length=1)
    reviewer_note: Optional[str] = None


DEFAULT_TOOLS: list[WorkbenchTool] = [
    WorkbenchTool(
        name="workbench_threads",
        category="workflow",
        summary="Local thread and message registry for supervised planning work.",
    ),
    WorkbenchTool(
        name="workbench_skills",
        category="workflow",
        summary="Local skill registry for repeatable operator workflows.",
    ),
    WorkbenchTool(
        name="workbench_memories",
        category="workflow",
        summary="Local memory records for review and continuity.",
    ),
    WorkbenchTool(
        name="workbench_artifacts",
        category="workflow",
        summary="Local artifact registry for proof, notes, and attachments.",
    ),
    WorkbenchTool(
        name="local_mcp",
        category="integration",
        summary="Local-only MCP tool layer.",
    ),
    WorkbenchTool(
        name="fake_worker_runner",
        category="execution",
        summary="Fake-worker-only execution surface for the current RC.",
    ),
]

DEFAULT_SAFETY_PROFILES: list[SafetyProfile] = [
    SafetyProfile(
        profile_id="operator_local",
        title="Operator Local",
        summary="Local-only supervised workflow profile with fake-worker-only execution.",
        notes="Real external agent launch is disabled.",
    ),
    SafetyProfile(
        profile_id="screenshot_sample",
        title="Screenshot Sample",
        summary="Preview profile for local cockpit screenshots and demos.",
        notes="Sample UI data is not executed.",
    ),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def redact_memory_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    text = _PRIVATE_KEY_BLOCK_RE.sub("[REDACTED PRIVATE KEY BLOCK]", text)
    text = _AUTH_HEADER_RE.sub(r"\1 [REDACTED]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _PASSWORD_FIELD_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return _TOKEN_RE.sub("[REDACTED]", text)


def _bounded_memory_text(value: Optional[str], limit: int = MAX_MEMORY_CONTENT_CHARS) -> Optional[str]:
    redacted = redact_memory_text(value)
    if redacted is None:
        return None
    return redacted.strip()[:limit]


def _safe_memory_tags(tags: list[str]) -> list[str]:
    clean: list[str] = []
    for raw_tag in tags[:32]:
        tag = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(raw_tag).strip().lower()).strip("-.")
        if tag and tag not in clean:
            clean.append(tag[:64])
    return clean


def _safe_memory_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in list(metadata.items())[:32]:
        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key))[:64]
        if not safe_key:
            continue
        if isinstance(value, str):
            safe[safe_key] = _bounded_memory_text(value, 1000)
        elif value is None or isinstance(value, (bool, int, float)):
            safe[safe_key] = value
        elif isinstance(value, list):
            safe[safe_key] = [
                _bounded_memory_text(str(item), 250) for item in value[:20]
            ]
    return safe


def _safe_id(value: str, field: str) -> str:
    if not re.match(SAFE_SLUG, value):
        raise WorkbenchError(f"invalid {field}: {value}")
    return value


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True, default=str)
        f.write("\n")
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_model(path: Path, model: type[BaseModel]) -> BaseModel:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


class WorkbenchStore:
    def __init__(self, root: str | Path = WORKBENCH_ROOT, ensure_layout: bool = True) -> None:
        self.root = Path(root).resolve()
        if ensure_layout:
            self.ensure_layout()

    def ensure_layout(self) -> None:
        for directory in [
            "agents",
            "threads",
            "messages",
            "runs",
            "skills",
            "memories",
            "artifacts",
        ]:
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        tools_path = self.root / "tools.json"
        if not tools_path.exists():
            _atomic_write_json(tools_path, [tool.model_dump(mode="json") for tool in DEFAULT_TOOLS])
        safety_path = self.root / "safety_profiles.json"
        if not safety_path.exists():
            _atomic_write_json(safety_path, [profile.model_dump(mode="json") for profile in DEFAULT_SAFETY_PROFILES])

    def _path(self, kind: str, item_id: str) -> Path:
        return self.root / kind / f"{item_id}.json"

    def _generate_thread_id(self, title: str) -> str:
        prefix = re.sub(r"[^A-Za-z0-9_-]+", "-", title.lower()).strip("-_")
        prefix = prefix[:24] or "thread"
        candidate = f"{prefix}-{uuid.uuid4().hex[:6]}"
        return _safe_id(candidate, "thread_id")

    def _generate_run_id(self, title: str) -> str:
        prefix = re.sub(r"[^A-Za-z0-9_-]+", "-", title.lower()).strip("-_")
        prefix = prefix[:24] or "run"
        candidate = f"run_{prefix}-{uuid.uuid4().hex[:6]}"
        return _safe_id(candidate, "run_id")

    def _generate_record_id(self, prefix: str, field: str) -> str:
        candidate = f"{prefix}_{uuid.uuid4().hex[:8]}"
        return _safe_id(candidate, field)

    def _generate_memory_id(self, title: str) -> str:
        prefix = re.sub(r"[^A-Za-z0-9_-]+", "-", title.lower()).strip("-_")
        prefix = prefix[:24] or "memory"
        candidate = f"m-{prefix}-{uuid.uuid4().hex[:6]}"
        return _safe_id(candidate, "memory_id")

    def _message_path(self, thread_id: str) -> Path:
        return self.root / "messages" / f"{thread_id}.jsonl"

    def _run_path(self, run_id: str) -> Path:
        return self._path("runs", _safe_id(run_id, "run_id"))

    def _load_run(self, run_id: str) -> WorkbenchRun:
        path = self._run_path(run_id)
        if not path.exists():
            raise WorkbenchError(f"run not available: {run_id}")
        return _load_model(path, WorkbenchRun)

    def _save_run(self, run: WorkbenchRun) -> WorkbenchRun:
        _atomic_write_json(self._run_path(run.run_id), run.model_dump(mode="json"))
        return run

    def _run_view(self, run: WorkbenchRun) -> dict[str, Any]:
        return run.model_dump(mode="json")

    def _run_events(self, run: WorkbenchRun) -> list[WorkbenchRunEvent]:
        return list(run.events)

    def _run_has_open_gate(self, run: WorkbenchRun) -> bool:
        return any(gate.status == "open" for gate in run.proof_gates)

    def _run_has_blocking_gate(self, run: WorkbenchRun) -> bool:
        return any(gate.status in {"open", "rejected", "blocked"} for gate in run.proof_gates)

    def _recompute_run_status(self, run: WorkbenchRun) -> None:
        if self._run_has_blocking_gate(run):
            run.status = "blocked"
            return
        if run.proof_gates and run.status == "blocked":
            run.status = "running"

    def _append_run_event(
        self,
        run: WorkbenchRun,
        *,
        event_type: Literal[
            "instruction",
            "plan",
            "minion_assignment",
            "tool_result",
            "evidence",
            "proof_gate",
            "approval",
            "blocked",
            "artifact",
            "note",
        ],
        title: str,
        detail: str,
        severity: Literal["info", "success", "warning", "blocked", "error"] = "info",
        event_id: Optional[str] = None,
    ) -> WorkbenchRunEvent:
        event = WorkbenchRunEvent(
            event_id=event_id or self._generate_record_id("event", "event_id"),
            run_id=run.run_id,
            thread_id=run.thread_id,
            event_type=event_type,
            title=title,
            detail=detail,
            severity=severity,
            created_at=_now(),
        )
        run.events.append(event)
        return event

    def _load_list_file(self, path: Path, model: type[BaseModel]) -> list[BaseModel]:
        if not path.exists():
            return []
        rows = _read_json(path)
        return [model.model_validate(item) for item in rows]

    def _save_list_file(self, path: Path, rows: list[BaseModel]) -> None:
        _atomic_write_json(path, [row.model_dump(mode="json") for row in rows])

    def _load_messages(self, thread_id: str) -> list[WorkbenchMessage]:
        path = self._message_path(thread_id)
        if not path.exists():
            return []
        rows: list[WorkbenchMessage] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(WorkbenchMessage.model_validate_json(line))
        return rows

    def _append_message(self, thread_id: str, message: WorkbenchMessage) -> None:
        path = self._message_path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(message.model_dump_json())
            f.write("\n")

    def _load_thread(self, thread_id: str) -> WorkbenchThread:
        path = self._path("threads", _safe_id(thread_id, "thread_id"))
        if not path.exists():
            raise WorkbenchError(f"thread not available: {thread_id}")
        return _load_model(path, WorkbenchThread)

    def _save_thread(self, thread: WorkbenchThread) -> WorkbenchThread:
        _atomic_write_json(self._path("threads", thread.thread_id), thread.model_dump(mode="json"))
        return thread

    def _thread_view(self, thread: WorkbenchThread) -> dict[str, Any]:
        messages = self._load_messages(thread.thread_id)
        blocked_gates = [gate for gate in thread.hard_gates if gate.blocked and gate.decision != "approve"]
        return {
            **thread.model_dump(mode="json"),
            "messages": [message.model_dump(mode="json") for message in messages],
            "message_count": len(messages),
            "proof_gate_count": len(thread.hard_gates),
            "blocked_gate_count": len(blocked_gates),
        }

    def list_agents(self) -> list[WorkbenchAgent]:
        self.ensure_layout()
        agents_dir = self.root / "agents"
        if not agents_dir.exists():
            return []
        rows: list[WorkbenchAgent] = []
        for path in sorted(agents_dir.glob("*.json")):
            try:
                rows.append(_load_model(path, WorkbenchAgent))
            except Exception:
                continue
        rows.sort(key=lambda item: item.updated_at, reverse=True)
        return rows

    def get_agent(self, agent_id: str) -> WorkbenchAgent:
        self.ensure_layout()
        path = self._path("agents", _safe_id(agent_id, "agent_id"))
        if not path.exists():
            raise WorkbenchError(f"agent not available: {agent_id}")
        return _load_model(path, WorkbenchAgent)

    def upsert_agent(self, payload: WorkbenchAgentCreateRequest) -> WorkbenchAgent:
        self.ensure_layout()
        _safe_id(payload.agent_id, "agent_id")
        if payload.safety_profile_id not in {profile.profile_id for profile in self.list_safety_profiles()}:
            raise WorkbenchError(f"safety profile not available: {payload.safety_profile_id}")
        agent = WorkbenchAgent(
            agent_id=payload.agent_id,
            name=payload.name,
            role=payload.role,
            status=payload.status,
            safety_profile_id=payload.safety_profile_id,
            allowed_threads=list(payload.allowed_threads),
            notes=payload.notes,
            created_at=_now(),
            updated_at=_now(),
        )
        _atomic_write_json(self._path("agents", agent.agent_id), agent.model_dump(mode="json"))
        return agent

    def list_threads(self) -> list[dict[str, Any]]:
        self.ensure_layout()
        threads_dir = self.root / "threads"
        if not threads_dir.exists():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(threads_dir.glob("*.json")):
            try:
                thread = _load_model(path, WorkbenchThread)
            except Exception:
                continue
            rows.append(
                {
                    **thread.model_dump(mode="json"),
                    "message_count": len(self._load_messages(thread.thread_id)),
                    "proof_gate_count": len(thread.hard_gates),
                }
            )
        rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return rows

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        self.ensure_layout()
        return self._thread_view(self._load_thread(thread_id))

    def create_thread(self, payload: WorkbenchThreadCreateRequest) -> dict[str, Any]:
        self.ensure_layout()
        objective = payload.objective or payload.goal
        if not objective:
            raise WorkbenchError("thread objective is required.")
        thread_id = payload.thread_id or self._generate_thread_id(payload.title)
        _safe_id(thread_id, "thread_id")
        if self._path("threads", thread_id).exists():
            raise WorkbenchError(f"thread already exists: {thread_id}")
        if payload.agent_id is not None:
            self.get_agent(payload.agent_id)
        thread = WorkbenchThread(
            thread_id=thread_id,
            agent_id=payload.agent_id,
            title=payload.title,
            objective=objective,
            status=payload.status,
            next_action=payload.next_action,
            prompt_queue=list(payload.prompt_queue),
            minion_tasks=list(payload.minion_tasks),
            evidence_records=list(payload.evidence_records),
            hard_gates=list(payload.hard_gates),
            scoped_commit_plan=payload.scoped_commit_plan,
            planned_acceptance_commands=list(payload.planned_acceptance_commands),
            recovery_hint=payload.recovery_hint,
            notes=payload.notes,
            metadata=dict(payload.metadata),
            created_at=_now(),
            updated_at=_now(),
        )
        if thread.hard_gates and any(gate.blocked and gate.decision != "approve" for gate in thread.hard_gates):
            thread.status = "blocked"
        self._save_thread(thread)
        return self._thread_view(thread)

    def update_thread(self, thread_id: str, payload: WorkbenchThreadUpdateRequest) -> dict[str, Any]:
        self.ensure_layout()
        thread = self._load_thread(thread_id)
        changed = False
        if payload.title is not None:
            thread.title = payload.title
            changed = True
        if payload.objective is not None:
            thread.objective = payload.objective
            changed = True
        if payload.status is not None:
            thread.status = payload.status
            changed = True
        if payload.next_action is not None:
            thread.next_action = payload.next_action
            changed = True
        if payload.recovery_hint is not None:
            thread.recovery_hint = payload.recovery_hint
            changed = True
        if payload.notes is not None:
            thread.notes = payload.notes
            changed = True
        if payload.metadata is not None:
            thread.metadata = dict(payload.metadata)
            changed = True
        if changed:
            thread.updated_at = _now()
            self._save_thread(thread)
        return self._thread_view(thread)

    def list_messages(self, thread_id: str) -> list[dict[str, Any]]:
        self.ensure_layout()
        self._load_thread(thread_id)
        return [message.model_dump(mode="json") for message in self._load_messages(thread_id)]

    def append_message(self, thread_id: str, payload: WorkbenchMessageCreateRequest) -> WorkbenchMessage:
        self.ensure_layout()
        thread = self._load_thread(thread_id)
        author = payload.author or payload.role or "operator"
        kind = payload.kind
        if kind == "instruction":
            kind = "planning"
        if kind == "command_request":
            raise WorkbenchError(
                "Command request messages are blocked in Workbench Core.",
            )
        message = WorkbenchMessage(
            message_id=payload.message_id or f"msg_{uuid.uuid4().hex[:8]}",
            thread_id=thread.thread_id,
            author=author,
            kind=kind,
            content=payload.content,
            status="recorded",
            created_at=_now(),
        )
        self._append_message(thread.thread_id, message)
        thread.updated_at = _now()
        self._save_thread(thread)
        return message

    def add_proof_gate(self, thread_id: str, payload: WorkbenchProofGateCreateRequest) -> dict[str, Any]:
        self.ensure_layout()
        thread = self._load_thread(thread_id)
        gate = HardGate(
            gate_id=f"gate_{uuid.uuid4().hex[:8]}",
            kind=payload.kind,
            reason=payload.reason,
            triggered_by=payload.triggered_by,
            blocked=True,
            created_at=_now(),
        )
        thread.hard_gates.append(gate)
        thread.status = "blocked"
        thread.updated_at = _now()
        self._save_thread(thread)
        return self._thread_view(thread)

    def decide_proof_gate(self, thread_id: str, gate_id: str, payload: WorkbenchProofGateDecisionRequest) -> dict[str, Any]:
        self.ensure_layout()
        thread = self._load_thread(thread_id)
        gate = next((item for item in thread.hard_gates if item.gate_id == gate_id), None)
        if gate is None:
            raise WorkbenchError(f"gate not available: {gate_id}")
        gate.decision = payload.decision
        gate.decision_actor = payload.actor
        gate.decision_note = payload.reviewer_note
        gate.decided_at = _now()
        gate.blocked = payload.decision != "approve"
        thread.status = "blocked" if any(item.blocked and item.decision != "approve" for item in thread.hard_gates) else "open"
        thread.updated_at = _now()
        self._save_thread(thread)
        return self._thread_view(thread)

    def list_runs(self) -> list[dict[str, Any]]:
        self.ensure_layout()
        runs_dir = self.root / "runs"
        if not runs_dir.exists():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(runs_dir.glob("*.json")):
            try:
                run = _load_model(path, WorkbenchRun)
            except Exception:
                continue
            rows.append(self._run_view(run))
        rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return rows

    def list_runs_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        self.ensure_layout()
        self._load_thread(thread_id)
        return [run for run in self.list_runs() if run.get("thread_id") == thread_id]

    def create_run(self, thread_id: str, payload: WorkbenchRunCreateRequest) -> WorkbenchRun:
        self.ensure_layout()
        thread = self._load_thread(thread_id)
        run_id = payload.run_id or self._generate_run_id(payload.title)
        _safe_id(run_id, "run_id")
        path = self._run_path(run_id)
        if path.exists():
            raise WorkbenchError(f"run already exists: {run_id}")
        now = _now()
        run = WorkbenchRun(
            run_id=run_id,
            thread_id=thread.thread_id,
            title=payload.title,
            status=payload.status,
            current_step=payload.current_step,
            created_at=now,
            updated_at=now,
            recovery_hint=payload.recovery_hint,
        )
        self._save_run(run)
        return run

    def get_run(self, run_id: str) -> WorkbenchRun:
        self.ensure_layout()
        return self._load_run(run_id)

    def list_run_events(self, run_id: str) -> list[WorkbenchRunEvent]:
        self.ensure_layout()
        return self._load_run(run_id).events

    def append_run_event(self, run_id: str, payload: WorkbenchRunEventCreateRequest) -> WorkbenchRunEvent:
        self.ensure_layout()
        run = self._load_run(run_id)
        event = WorkbenchRunEvent(
            event_id=payload.event_id or self._generate_record_id("event", "event_id"),
            run_id=run.run_id,
            thread_id=run.thread_id,
            event_type=payload.event_type,
            title=payload.title,
            detail=payload.detail,
            severity=payload.severity,
            created_at=_now(),
        )
        run.events.append(event)
        run.updated_at = _now()
        self._save_run(run)
        return event

    def list_run_evidence(self, run_id: str) -> list[EvidenceRecord]:
        self.ensure_layout()
        return self._load_run(run_id).evidence_records

    def add_run_evidence(self, run_id: str, payload: WorkbenchEvidenceRecordCreateRequest) -> EvidenceRecord:
        self.ensure_layout()
        run = self._load_run(run_id)
        evidence = EvidenceRecord(
            evidence_id=payload.evidence_id or self._generate_record_id("evidence", "evidence_id"),
            run_id=run.run_id,
            thread_id=run.thread_id,
            title=payload.title,
            summary=payload.summary,
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            verdict=payload.verdict,
            created_at=_now(),
        )
        run.evidence_records.append(evidence)
        self._append_run_event(
            run,
            event_type="evidence",
            title=payload.title,
            detail=payload.summary,
            severity="success" if payload.verdict == "passed" else "warning" if payload.verdict == "unknown" else "blocked" if payload.verdict == "blocked" else "error",
        )
        run.updated_at = _now()
        self._save_run(run)
        return evidence

    def list_proof_gates(self, run_id: str) -> list[ProofGate]:
        self.ensure_layout()
        return self._load_run(run_id).proof_gates

    def open_run_proof_gate(self, run_id: str, payload: WorkbenchRunProofGateCreateRequest) -> ProofGate:
        self.ensure_layout()
        run = self._load_run(run_id)
        gate = ProofGate(
            gate_id=payload.gate_id or self._generate_record_id("gate", "gate_id"),
            run_id=run.run_id,
            thread_id=run.thread_id,
            title=payload.title,
            reason=payload.reason,
            status="open",
            requires_human=payload.requires_human,
            created_at=_now(),
        )
        run.proof_gates.append(gate)
        run.status = "blocked"
        self._append_run_event(
            run,
            event_type="proof_gate",
            title=gate.title,
            detail=gate.reason,
            severity="blocked",
        )
        run.updated_at = _now()
        self._save_run(run)
        return gate

    def decide_run_proof_gate(self, gate_id: str, payload: WorkbenchRunProofGateDecisionRequest) -> dict[str, Any]:
        self.ensure_layout()
        run = None
        gate = None
        for candidate_path in sorted((self.root / "runs").glob("*.json")):
            try:
                candidate = _load_model(candidate_path, WorkbenchRun)
            except Exception:
                continue
            gate = next((item for item in candidate.proof_gates if item.gate_id == gate_id), None)
            if gate is not None:
                run = candidate
                break
        if run is None or gate is None:
            raise WorkbenchError(f"gate not available: {gate_id}")
        decision = ApprovalDecision(
            decision_id=self._generate_record_id("decision", "decision_id"),
            gate_id=gate.gate_id,
            run_id=run.run_id,
            thread_id=run.thread_id,
            actor=payload.actor,
            decision=payload.decision,
            note=payload.note,
            created_at=_now(),
        )
        run.approval_decisions.append(decision)
        gate.decision_id = decision.decision_id
        gate.decided_at = decision.created_at
        if payload.decision == "approved":
            gate.status = "approved"
        elif payload.decision == "rejected":
            gate.status = "rejected"
        else:
            gate.status = "blocked"
        run.status = "blocked" if self._run_has_blocking_gate(run) else "running"
        self._append_run_event(
            run,
            event_type="approval",
            title=f"Gate {payload.decision}",
            detail=payload.note or f"{payload.actor} recorded {payload.decision}.",
            severity="success" if payload.decision == "approved" else "blocked",
        )
        run.updated_at = _now()
        self._save_run(run)
        return self._run_view(run)

    def continue_run(self, run_id: str) -> dict[str, Any]:
        self.ensure_layout()
        run = self._load_run(run_id)
        if self._run_has_open_gate(run):
            self._append_run_event(
                run,
                event_type="blocked",
                title="Continuation blocked",
                detail="Approve/reject the open proof gates before continuing.",
                severity="blocked",
            )
            run.status = "blocked"
            run.updated_at = _now()
            self._save_run(run)
            return {
                "status": "blocked",
                "reason": "Open proof gates block continuation.",
                "recovery_hint": "Approve/reject the open proof gates before continuing.",
                "run": self._run_view(run),
            }
        if any(gate.status in {"rejected", "blocked"} for gate in run.proof_gates):
            self._append_run_event(
                run,
                event_type="blocked",
                title="Continuation blocked",
                detail="Resolve the rejected or edit-requested proof gates before continuing.",
                severity="blocked",
            )
            run.status = "blocked"
            run.updated_at = _now()
            self._save_run(run)
            return {
                "status": "blocked",
                "reason": "Rejected or edit-requested proof gates block continuation.",
                "recovery_hint": "Resolve the proof gates before continuing.",
                "run": self._run_view(run),
            }
        self._append_run_event(
            run,
            event_type="note",
            title="Safe noop",
            detail="Continuation is not wired to real execution in the public RC.",
            severity="info",
        )
        run.updated_at = _now()
        self._save_run(run)
        return {
            "status": "safe_noop",
            "reason": "Continuation is not wired to real execution in the public RC.",
            "recovery_hint": "Use fake-worker-only tasks or record manual evidence.",
            "run": self._run_view(run),
        }

    def list_skills(self) -> list[WorkbenchSkill]:
        self.ensure_layout()
        skills_dir = self.root / "skills"
        rows: list[WorkbenchSkill] = []
        if not skills_dir.exists():
            return rows
        for path in sorted(skills_dir.glob("*.json")):
            try:
                rows.append(_load_model(path, WorkbenchSkill))
            except Exception:
                continue
        rows.sort(key=lambda item: item.updated_at, reverse=True)
        return rows

    def get_skill(self, skill_id: str) -> WorkbenchSkill:
        self.ensure_layout()
        path = self._path("skills", _safe_id(skill_id, "skill_id"))
        if not path.exists():
            raise WorkbenchError(f"skill not available: {skill_id}")
        return _load_model(path, WorkbenchSkill)

    def create_skill(self, payload: WorkbenchSkillCreateRequest) -> WorkbenchSkill:
        self.ensure_layout()
        _safe_id(payload.skill_id, "skill_id")
        if self._path("skills", payload.skill_id).exists():
            raise WorkbenchError(f"skill already exists: {payload.skill_id}")
        skill = WorkbenchSkill(
            skill_id=payload.skill_id,
            title=payload.title,
            description=payload.description,
            path=payload.path,
            enabled=payload.enabled,
            notes=payload.notes,
            when_to_use=payload.when_to_use,
            inspect_files=payload.inspect_files,
            commands_allowed=payload.commands_allowed,
            commands_forbidden=payload.commands_forbidden,
            proof_format=payload.proof_format,
            acceptance_checks=payload.acceptance_checks,
            rollback_notes=payload.rollback_notes,
            report_template=payload.report_template,
            created_at=_now(),
            updated_at=_now(),
        )
        _atomic_write_json(self._path("skills", skill.skill_id), skill.model_dump(mode="json"))
        return skill

    def list_memories(self) -> list[WorkbenchMemory]:
        self.ensure_layout()
        memories_dir = self.root / "memories"
        rows: list[WorkbenchMemory] = []
        if not memories_dir.exists():
            return rows
        for path in sorted(memories_dir.glob("*.json")):
            try:
                rows.append(_load_model(path, WorkbenchMemory))
            except Exception:
                continue
        rows.sort(key=lambda item: item.updated_at, reverse=True)
        return rows

    def _memory_search_text(self, memory: WorkbenchMemory) -> str:
        # Include flattened metadata so plan_id, goal, source=local_preview etc. are searchable
        meta_text = ""
        if memory.metadata and isinstance(memory.metadata, dict):
            meta_parts = []
            for v in memory.metadata.values():
                if isinstance(v, str):
                    meta_parts.append(v)
                elif isinstance(v, (int, float)):
                    meta_parts.append(str(v))
                elif isinstance(v, list):
                    meta_parts.extend(str(i) for i in v if isinstance(i, str))
            meta_text = " ".join(meta_parts)
        return " ".join(
            [
                memory.memory_id,
                memory.scope,
                memory.title or "",
                memory.summary,
                memory.source,
                memory.source_ref or "",
                " ".join(memory.tags),
                memory.kind,
                memory.status,
                memory.project_id or "",
                memory.repo_path or "",
                memory.branch or "",
                memory.task_id or "",
                memory.agent_id or "",
                memory.notes or "",
                meta_text,
            ]
        ).lower()

    # Keywords that signal the user wants the most recent plan/decision
    _RECENCY_SIGNALS = frozenset({"just", "latest", "recent", "last", "new", "created", "today"})
    # Sources that get a relevance boost for plan-related queries
    _PLAN_SOURCES = frozenset({"captain", "captain_dispatch", "agent_dispatcher"})
    # Terms that signal interest in agent runs / dispatch actions
    _RUN_SIGNALS = frozenset({"run", "agent", "dispatch", "dispatched", "blocked", "proof", "executed", "step", "did"})
    # Memory kinds that represent dispatch/run outcomes
    _DISPATCH_KINDS = frozenset({"blocked_attempt", "agent_result", "proof", "test_result"})

    def search_memories(
        self,
        query: str,
        *,
        scope: Optional[str] = None,
        limit: int = 20,
    ) -> list[WorkbenchMemory]:
        self.ensure_layout()
        query = query.strip().lower()
        rows = self.list_memories()
        if scope:
            rows = [memory for memory in rows if memory.scope.lower() == scope.strip().lower()]
        rows = [memory for memory in rows if memory.status != "forgotten"]
        if not query or query == "*":
            return rows[:limit]

        terms = [term for term in re.split(r"\s+", query) if term and len(term) > 1]
        wants_recent = bool(self._RECENCY_SIGNALS.intersection(terms))
        wants_plan = any(t in ("plan", "captain", "plans") for t in terms)
        wants_run = any(t in self._RUN_SIGNALS for t in terms)

        scored: list[tuple[int, float, str, WorkbenchMemory]] = []
        for memory in rows:
            haystack = self._memory_search_text(memory)
            if query in haystack:
                score = 100 + haystack.count(query)
            else:
                score = sum(10 for term in terms if term in haystack)
            if score == 0:
                continue

            # Boost: captain/plan source when query is about plans
            if wants_plan and memory.source in self._PLAN_SOURCES:
                score += 25
            # Boost: recency signal words + captain source = surface newest plan first
            if wants_recent and memory.source in self._PLAN_SOURCES:
                score += 20
            # Boost: decision/handoff kind for plan queries
            if wants_plan and memory.kind in ("decision", "handoff", "agent_result"):
                score += 15
            # Boost: dispatch/run kinds for agent-run queries
            if wants_run and memory.kind in self._DISPATCH_KINDS:
                score += 30
            if wants_run and memory.source in self._PLAN_SOURCES:
                score += 20
            # Always boost dispatch memories when recency is requested
            if wants_recent and memory.kind in self._DISPATCH_KINDS:
                score += 25

            scored.append((score, memory.updated_at.timestamp(), memory.memory_id, memory))

        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [memory for _, _, _, memory in scored[:limit]]

    def create_memory(self, payload: WorkbenchMemoryCreateRequest) -> WorkbenchMemory:
        self.ensure_layout()
        summary = _bounded_memory_text(payload.summary)
        if not summary:
            raise WorkbenchError("memory summary is required.")
        memory_id = payload.memory_id or self._generate_memory_id(summary)
        _safe_id(memory_id, "memory_id")
        if self._path("memories", memory_id).exists():
            raise WorkbenchError(f"memory already exists: {memory_id}")
        scope = _bounded_memory_text(payload.scope, 160)
        if not scope:
            raise WorkbenchError("memory scope is required.")
        title = _bounded_memory_text(payload.title or summary[:80], 160)
        memory = WorkbenchMemory(
            memory_id=memory_id,
            scope=scope,
            summary=summary,
            source=_bounded_memory_text(payload.source, 80) or "warden",
            title=title,
            source_ref=_bounded_memory_text(payload.source_ref, 500),
            tags=_safe_memory_tags(payload.tags),
            kind=payload.kind,
            status=payload.status,
            confidence=payload.confidence,
            project_id=_bounded_memory_text(payload.project_id, 160),
            repo_path=_bounded_memory_text(payload.repo_path, 500),
            branch=_bounded_memory_text(payload.branch, 200),
            task_id=_bounded_memory_text(payload.task_id, 160),
            agent_id=_bounded_memory_text(payload.agent_id, 80),
            metadata=_safe_memory_metadata(payload.metadata),
            compacted=payload.compacted,
            notes=_bounded_memory_text(payload.notes, 2000),
            raw_content=_bounded_memory_text(payload.raw_content),
            raw_content_truncated=payload.raw_content_truncated
            or bool(payload.raw_content and len(payload.raw_content) > MAX_MEMORY_CONTENT_CHARS),
            created_at=_now(),
            updated_at=_now(),
        )
        _atomic_write_json(self._path("memories", memory.memory_id), memory.model_dump(mode="json"))
        return memory

    def remember_memory(self, payload: WorkbenchMemoryRememberRequest) -> WorkbenchMemory:
        self.ensure_layout()
        summary = payload.content.strip()
        memory_id = payload.memory_id or self._generate_memory_id(summary)
        create_payload = WorkbenchMemoryCreateRequest(
            memory_id=memory_id,
            scope=payload.scope,
            summary=summary,
            source=payload.source,
            title=payload.title or summary[:80],
            source_ref=payload.source_ref,
            tags=list(payload.tags),
            kind=payload.kind,
            status=payload.status,
            confidence=payload.confidence,
            project_id=payload.project_id,
            repo_path=payload.repo_path,
            branch=payload.branch,
            task_id=payload.task_id,
            agent_id=payload.agent_id,
            metadata=dict(payload.metadata),
            compacted=payload.compacted,
            notes=payload.notes,
        )
        return self.create_memory(create_payload)

    def get_memory(self, memory_id: str) -> WorkbenchMemory:
        self.ensure_layout()
        path = self._path("memories", _safe_id(memory_id, "memory_id"))
        if not path.exists():
            raise WorkbenchError(f"memory not available: {memory_id}")
        return _load_model(path, WorkbenchMemory)

    def update_memory_promotion(
        self,
        memory_id: str,
        *,
        status: Optional[str] = None,
        source_ref: Optional[str] = None,
    ) -> WorkbenchMemory:
        """v2.4 promotion/discard support: set a memory's status and/or vault source_ref."""
        memory = self.get_memory(memory_id)
        if status is not None:
            if status not in ("active", "superseded", "stale", "forgotten"):
                raise WorkbenchError(f"invalid memory status: {status}")
            memory.status = status  # type: ignore[assignment]
        if source_ref is not None:
            memory.source_ref = _bounded_memory_text(source_ref, 500)
        memory.updated_at = _now()
        _atomic_write_json(self._path("memories", memory.memory_id), memory.model_dump(mode="json"))
        return memory

    def build_memory_context_pack(
        self,
        *,
        project_id: str,
        repo_path: Optional[str] = None,
        agent: Optional[str] = None,
        user_prompt: str = "",
        branch: Optional[str] = None,
        task_id: Optional[str] = None,
        max_memories: int = DEFAULT_CONTEXT_MAX_MEMORIES,
        max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
    ) -> dict[str, Any]:
        scope = project_id.strip()
        max_memories = max(1, min(int(max_memories), 50))
        max_chars = max(256, min(int(max_chars), 20_000))
        query_terms = {
            term
            for term in re.findall(r"[a-z0-9_.-]{3,}", (user_prompt or "").lower())
        }
        priority = {
            "constraint": 90,
            "decision": 85,
            "failure": 80,
            "blocked_attempt": 78,
            "proof": 75,
            "test_result": 72,
            "fragile_file": 70,
            "acceptance_test": 68,
            "handoff": 65,
            "claim": 55,
        }
        ranked: list[tuple[int, float, str, WorkbenchMemory]] = []
        for memory in self.list_memories():
            if memory.status != "active":
                continue
            scope_matches = memory.scope.lower() == scope.lower()
            project_matches = bool(memory.project_id and memory.project_id.lower() == scope.lower())
            repo_matches = bool(repo_path and memory.repo_path and memory.repo_path == repo_path)
            if not (scope_matches or project_matches or repo_matches):
                continue
            haystack = self._memory_search_text(memory)
            query_score = sum(8 for term in query_terms if term in haystack)
            agent_score = 5 if agent and memory.agent_id and memory.agent_id.lower() == agent.lower() else 0
            task_score = 5 if task_id and memory.task_id == task_id else 0
            branch_score = 3 if branch and memory.branch == branch else 0
            score = priority.get(memory.kind, 40) + query_score + agent_score + task_score + branch_score
            ranked.append((score, memory.updated_at.timestamp(), memory.memory_id, memory))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        selected = [item[3] for item in ranked[:max_memories]]
        if not selected:
            return {
                "context": "",
                "memory_count": 0,
                "memory_ids": [],
                "truncated": False,
                "scope": scope,
            }

        section_for_kind = {
            "decision": "Relevant Decisions",
            "failure": "Prior Failures / Avoid",
            "blocked_attempt": "Prior Failures / Avoid",
            "proof": "Proven State",
            "test_result": "Proven State",
            "claim": "Claimed But Unproven",
            "constraint": "Known Constraints",
            "fragile_file": "Fragile Files / Hot Spots",
            "acceptance_test": "Suggested Acceptance Tests",
            "handoff": "Handoff / Next Step",
        }
        sections: dict[str, list[str]] = {}
        for memory in selected:
            heading = section_for_kind.get(memory.kind, "Relevant Project Context")
            summary = _bounded_memory_text(memory.summary, 800) or ""
            sections.setdefault(heading, []).append(
                f"- [{memory.memory_id}] {memory.title or memory.kind}: {summary}"
            )

        lines = [
            "# Warden Memory Context",
            "",
            "## Project / Repo",
            f"- Project: {redact_memory_text(scope)}",
        ]
        if repo_path:
            lines.append(f"- Repo: {redact_memory_text(repo_path)}")
        if branch:
            lines.append(f"- Branch: {redact_memory_text(branch)}")
        for heading in [
            "Relevant Decisions",
            "Prior Failures / Avoid",
            "Proven State",
            "Claimed But Unproven",
            "Known Constraints",
            "Fragile Files / Hot Spots",
            "Suggested Acceptance Tests",
            "Handoff / Next Step",
            "Relevant Project Context",
        ]:
            entries = sections.get(heading)
            if entries:
                lines.extend(["", f"## {heading}", *entries])
        lines.extend(["", "## Source Memories"])
        lines.extend(f"- {memory.memory_id}: {memory.title or memory.kind}" for memory in selected)
        context = redact_memory_text("\n".join(lines).strip()) or ""
        truncated = len(context) > max_chars
        if truncated:
            suffix = "\n\n[Warden Memory context truncated]"
            context = context[: max(0, max_chars - len(suffix))].rstrip() + suffix
        return {
            "context": context,
            "memory_count": len(selected),
            "memory_ids": [memory.memory_id for memory in selected],
            "truncated": truncated,
            "scope": scope,
        }

    def list_artifacts(self) -> list[WorkbenchArtifact]:
        self.ensure_layout()
        artifacts_dir = self.root / "artifacts"
        rows: list[WorkbenchArtifact] = []
        if not artifacts_dir.exists():
            return rows
        for path in sorted(artifacts_dir.glob("*.json")):
            try:
                rows.append(_load_model(path, WorkbenchArtifact))
            except Exception:
                continue
        rows.sort(key=lambda item: item.updated_at, reverse=True)
        return rows

    def create_artifact(self, payload: WorkbenchArtifactCreateRequest) -> WorkbenchArtifact:
        self.ensure_layout()
        _safe_id(payload.artifact_id, "artifact_id")
        if payload.thread_id is not None:
            self._load_thread(payload.thread_id)
        if self._path("artifacts", payload.artifact_id).exists():
            raise WorkbenchError(f"artifact already exists: {payload.artifact_id}")
        artifact = WorkbenchArtifact(
            artifact_id=payload.artifact_id,
            thread_id=payload.thread_id,
            kind=payload.kind,
            title=payload.title,
            path=payload.path,
            summary=payload.summary,
            notes=payload.notes,
            created_at=_now(),
            updated_at=_now(),
        )
        _atomic_write_json(self._path("artifacts", artifact.artifact_id), artifact.model_dump(mode="json"))
        return artifact

    def list_tools(self) -> list[WorkbenchTool]:
        self.ensure_layout()
        return self._load_list_file(self.root / "tools.json", WorkbenchTool)

    def list_safety_profiles(self) -> list[SafetyProfile]:
        self.ensure_layout()
        return self._load_list_file(self.root / "safety_profiles.json", SafetyProfile)

    def status(self) -> dict[str, Any]:
        self.ensure_layout()
        threads = self.list_threads()
        runs = self.list_runs()
        messages = sum(len(self.list_messages(item["thread_id"])) for item in threads)
        gates = sum(int(item.get("proof_gate_count", 0)) for item in threads)
        run_events = sum(len(item.get("events", [])) for item in runs)
        run_evidence = sum(len(item.get("evidence_records", [])) for item in runs)
        run_gates = sum(len(item.get("proof_gates", [])) for item in runs)
        return {
            "service": "marius-workbench",
            "status": "online",
            "local_only": True,
            "fake_worker_only": True,
            "real_agent_launch_disabled": True,
            "arbitrary_command_execution_disabled": True,
            "agents": len(self.list_agents()),
            "threads": len(threads),
            "messages": messages,
            "runs": len(runs),
            "run_events": run_events,
            "run_evidence": run_evidence,
            "run_proof_gates": run_gates,
            "skills": len(self.list_skills()),
            "memories": len(self.list_memories()),
            "artifacts": len(self.list_artifacts()),
            "proof_gates": gates,
            "tools": len(self.list_tools()),
            "safety_profiles": len(self.list_safety_profiles()),
            "workbench_root": str(self.root),
        }


router = APIRouter(prefix="/workbench", tags=["marius-desktop-workbench"])
STORE = WorkbenchStore()


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkbenchError):
        detail = str(exc)
        status_code = 404 if "not available" in detail or "does not exist" in detail else 400
        return HTTPException(status_code=status_code, detail=detail)
    raise exc


@router.get("/status")
def get_status() -> dict[str, Any]:
    return STORE.status()


@router.get("/agents", response_model=list[WorkbenchAgent])
def get_agents() -> list[WorkbenchAgent]:
    return STORE.list_agents()


@router.post("/agents", response_model=WorkbenchAgent)
def create_agent(payload: WorkbenchAgentCreateRequest) -> WorkbenchAgent:
    try:
        return STORE.upsert_agent(payload)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/agents/{agent_id}", response_model=WorkbenchAgent)
def get_agent(agent_id: str) -> WorkbenchAgent:
    try:
        return STORE.get_agent(agent_id)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/threads")
def get_threads() -> list[dict[str, Any]]:
    return STORE.list_threads()


@router.post("/threads")
def create_thread(payload: WorkbenchThreadCreateRequest) -> dict[str, Any]:
    try:
        return STORE.create_thread(payload)
    except Exception as exc:
        raise _http_error(exc)


@router.patch("/threads/{thread_id}")
def patch_thread(thread_id: str, payload: WorkbenchThreadUpdateRequest) -> dict[str, Any]:
    try:
        return STORE.update_thread(thread_id, payload)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str) -> dict[str, Any]:
    try:
        return STORE.get_thread(thread_id)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/threads/{thread_id}/runs")
def get_thread_runs(thread_id: str) -> list[dict[str, Any]]:
    try:
        return STORE.list_runs_for_thread(thread_id)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/threads/{thread_id}/messages")
def get_thread_messages(thread_id: str) -> list[dict[str, Any]]:
    try:
        return STORE.list_messages(thread_id)
    except Exception as exc:
        raise _http_error(exc)


@router.post("/threads/{thread_id}/messages", response_model=WorkbenchMessage)
def post_thread_message(thread_id: str, payload: WorkbenchMessageCreateRequest) -> WorkbenchMessage:
    try:
        return STORE.append_message(thread_id, payload)
    except Exception as exc:
        if isinstance(exc, WorkbenchError) and "blocked" in str(exc).lower():
            return JSONResponse(
                status_code=400,
                content={
                    "status": "blocked",
                    "reason": str(exc),
                    "recovery_hint": "Use planning, note, evidence, or system messages instead.",
                },
            )
        raise _http_error(exc)


@router.get("/threads/{thread_id}/proof-gates")
def get_thread_proof_gates(thread_id: str) -> list[dict[str, Any]]:
    try:
        return STORE.get_thread(thread_id)["hard_gates"]
    except Exception as exc:
        raise _http_error(exc)


@router.post("/threads/{thread_id}/proof-gates")
def post_thread_proof_gate(thread_id: str, payload: WorkbenchProofGateCreateRequest) -> dict[str, Any]:
    try:
        return STORE.add_proof_gate(thread_id, payload)
    except Exception as exc:
        raise _http_error(exc)


@router.post("/threads/{thread_id}/proof-gates/{gate_id}/decision")
def post_thread_proof_gate_decision(
    thread_id: str,
    gate_id: str,
    payload: WorkbenchProofGateDecisionRequest,
) -> dict[str, Any]:
    try:
        return STORE.decide_proof_gate(thread_id, gate_id, payload)
    except Exception as exc:
        raise _http_error(exc)


@router.post("/threads/{thread_id}/captain-runs", response_model=dict[str, Any])
def create_thread_captain_run(thread_id: str, payload: WorkbenchCaptainRunCreateRequest) -> dict[str, Any]:
    try:
        from .captain import create_captain_state_machine_run

        return create_captain_state_machine_run(thread_id, payload.objective).model_dump(mode="json")
    except Exception as exc:
        raise _http_error(exc)


@router.get("/runs", response_model=list[WorkbenchRun])
def get_runs() -> list[WorkbenchRun]:
    return [WorkbenchRun.model_validate(run) for run in STORE.list_runs()]


@router.post("/threads/{thread_id}/runs", response_model=WorkbenchRun)
def create_run(thread_id: str, payload: WorkbenchRunCreateRequest) -> WorkbenchRun:
    try:
        return STORE.create_run(thread_id, payload)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/runs/{run_id}", response_model=WorkbenchRun)
def get_run(run_id: str) -> WorkbenchRun:
    try:
        return STORE.get_run(run_id)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/runs/{run_id}/events", response_model=list[WorkbenchRunEvent])
def get_run_events(run_id: str) -> list[WorkbenchRunEvent]:
    try:
        return STORE.list_run_events(run_id)
    except Exception as exc:
        raise _http_error(exc)


@router.post("/runs/{run_id}/events", response_model=WorkbenchRun)
def post_run_event(run_id: str, payload: WorkbenchRunEventCreateRequest) -> WorkbenchRun:
    try:
        STORE.append_run_event(run_id, payload)
        return STORE.get_run(run_id)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceRecord])
def get_run_evidence(run_id: str) -> list[EvidenceRecord]:
    try:
        return STORE.list_run_evidence(run_id)
    except Exception as exc:
        raise _http_error(exc)


@router.post("/runs/{run_id}/evidence", response_model=WorkbenchRun)
def post_run_evidence(run_id: str, payload: WorkbenchEvidenceRecordCreateRequest) -> WorkbenchRun:
    try:
        STORE.add_run_evidence(run_id, payload)
        return STORE.get_run(run_id)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/runs/{run_id}/proof-gates", response_model=list[ProofGate])
def get_run_proof_gates(run_id: str) -> list[ProofGate]:
    try:
        return STORE.list_proof_gates(run_id)
    except Exception as exc:
        raise _http_error(exc)


@router.post("/runs/{run_id}/proof-gates", response_model=WorkbenchRun)
def post_run_proof_gate(run_id: str, payload: WorkbenchRunProofGateCreateRequest) -> WorkbenchRun:
    try:
        STORE.open_run_proof_gate(run_id, payload)
        return STORE.get_run(run_id)
    except Exception as exc:
        raise _http_error(exc)


@router.post("/proof-gates/{gate_id}/decision", response_model=WorkbenchRun)
def post_run_proof_gate_decision(gate_id: str, payload: WorkbenchRunProofGateDecisionRequest) -> WorkbenchRun:
    try:
        return STORE.decide_run_proof_gate(gate_id, payload)
    except Exception as exc:
        raise _http_error(exc)


@router.post("/runs/{run_id}/continue")
def continue_run(run_id: str) -> dict[str, Any]:
    try:
        return STORE.continue_run(run_id)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/skills", response_model=list[WorkbenchSkill])
def get_skills() -> list[WorkbenchSkill]:
    return STORE.list_skills()


@router.post("/skills", response_model=WorkbenchSkill)
def create_skill(payload: WorkbenchSkillCreateRequest) -> WorkbenchSkill:
    try:
        return STORE.create_skill(payload)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/skills/{skill_id}", response_model=WorkbenchSkill)
def get_skill(skill_id: str) -> WorkbenchSkill:
    try:
        return STORE.get_skill(skill_id)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/memories", response_model=list[WorkbenchMemory])
def get_memories() -> list[WorkbenchMemory]:
    return STORE.list_memories()


@router.post("/memories", response_model=WorkbenchMemory)
def create_memory(payload: WorkbenchMemoryCreateRequest) -> WorkbenchMemory:
    try:
        return STORE.create_memory(payload)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/artifacts", response_model=list[WorkbenchArtifact])
def get_artifacts() -> list[WorkbenchArtifact]:
    return STORE.list_artifacts()


@router.post("/artifacts", response_model=WorkbenchArtifact)
def create_artifact(payload: WorkbenchArtifactCreateRequest) -> WorkbenchArtifact:
    try:
        return STORE.create_artifact(payload)
    except Exception as exc:
        raise _http_error(exc)


@router.get("/tools", response_model=list[WorkbenchTool])
def get_tools() -> list[WorkbenchTool]:
    return STORE.list_tools()


@router.get("/safety-profiles", response_model=list[SafetyProfile])
def get_safety_profiles() -> list[SafetyProfile]:
    return STORE.list_safety_profiles()
