from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .contracts import (
    CaptainRun,
    CaptainTemplate,
    EvidenceRecord,
    HardGate,
    MinionTask,
    PromptQueueItem as WorkflowPromptQueueItem,
    ScopedCommitPlan,
)
from .workbench import (
    STORE as WORKBENCH_STORE,
    WorkbenchRunCreateRequest,
    WorkbenchEvidenceRecordCreateRequest,
    WorkbenchRunEventCreateRequest,
    WorkbenchRunProofGateCreateRequest,
)

from src.warden.paths import data_root as _warden_data_root
MCTABLE_ROOT = _warden_data_root()
CAPTAIN_ROOT = MCTABLE_ROOT / "captain"
RUNS_DIR = CAPTAIN_ROOT / "runs"
FILE_LOCK = threading.Lock()

router = APIRouter(prefix="/captain", tags=["marius-desktop-captain"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _run_path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.json"


def _load_run(run_id: str) -> CaptainRun:
    path = _run_path(run_id)
    if not path.exists():
        raise FileNotFoundError(run_id)
    return CaptainRun.model_validate_json(path.read_text(encoding="utf-8"))


def _save_run(run: CaptainRun) -> CaptainRun:
    _ensure_dirs()
    _run_path(run.run_id).write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return run


def _update_run(run_id: str, updater) -> CaptainRun:
    with FILE_LOCK:
        run = _load_run(run_id)
        updated = updater(run)
        updated.updated_at = _now()
        return _save_run(updated)


class CaptainRunCreateRequest(BaseModel):
    objective: str
    next_action: str = "inspect"
    prompt_queue: list[WorkflowPromptQueueItem] = Field(default_factory=list)
    minion_tasks: list[MinionTask] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    hard_gates: list[HardGate] = Field(default_factory=list)
    scoped_commit_plan: Optional[ScopedCommitPlan] = None
    planned_acceptance_commands: list[str] = Field(default_factory=list)


class EvidenceCreateRequest(BaseModel):
    kind: Optional[str] = None
    summary: str
    status: Optional[str] = None
    command_text: Optional[str] = None
    details: Optional[str] = None
    captured_by: str
    artifacts: list[str] = Field(default_factory=list)


class GateCreateRequest(BaseModel):
    kind: str
    reason: str
    triggered_by: str


class GateDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "edit_state"]
    actor: str
    reviewer_note: Optional[str] = None


class CaptainNextRequest(BaseModel):
    next_action: str
    planned_acceptance_commands: list[str] = Field(default_factory=list)
    command_execution_request: bool = False


class CaptainTemplateRunRequest(BaseModel):
    template: CaptainTemplate
    next_action: str = "inspect"
    command_execution_request: bool = False


class CaptainState(BaseModel):
    captain_run_id: str
    thread_id: str
    run_id: str
    status: Literal[
        "intake",
        "planning",
        "queued",
        "assigning",
        "waiting_for_evidence",
        "blocked_on_gate",
        "ready_to_continue",
        "completed",
        "failed",
        "cancelled",
    ] = "intake"
    objective: str
    current_step: str
    created_at: datetime
    updated_at: datetime
    recovery_hint: Optional[str] = None
    plan: Optional["CaptainPlan"] = None
    prompt_queue: list["PromptQueueItem"] = Field(default_factory=list)
    assignments: list["MinionAssignment"] = Field(default_factory=list)
    transitions: list["CaptainTransition"] = Field(default_factory=list)
    proof_gate_id: Optional[str] = None


class CaptainPlan(BaseModel):
    plan_id: str
    captain_run_id: str
    summary: str
    assumptions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    requires_human_gate: bool = True
    created_at: datetime


class PromptQueueItem(BaseModel):
    queue_item_id: str
    captain_run_id: str
    title: str
    prompt: str
    status: Literal["queued", "assigned", "evidence_required", "blocked", "completed", "cancelled"] = "queued"
    priority: int = 1
    target_role: Literal["ui_inspector", "safety_auditor", "test_runner", "implementer", "docs_writer", "reviewer"] = "reviewer"
    dependencies: list[str] = Field(default_factory=list)
    file_scope: list[str] = Field(default_factory=list)
    forbidden_file_scope: list[str] = Field(default_factory=list)
    max_attempts: int = 2
    attempt_count: int = 0
    evidence_required: list[str] = Field(default_factory=list)
    export_format: Literal["codex_cli", "agy_cli", "generic_markdown"] = "generic_markdown"
    export_text: str = ""
    allowed_files: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MinionAssignment(BaseModel):
    assignment_id: str
    captain_run_id: str
    queue_item_id: str
    role: Literal["ui_inspector", "safety_auditor", "test_runner", "implementer", "docs_writer", "reviewer"]
    title: str
    instructions: str
    status: Literal["assigned", "waiting_for_result", "evidence_submitted", "blocked", "completed", "failed"] = "assigned"
    may_edit: bool = False
    may_commit: bool = False
    may_execute_shell: bool = False
    must_return_evidence: bool = True
    handoff_prompt: str = ""
    evidence_required: list[str] = Field(default_factory=list)
    output_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CaptainTransition(BaseModel):
    transition_id: str
    captain_run_id: str
    from_status: str
    to_status: str
    reason: str
    created_at: datetime


class CaptainRunStateMachineCreateRequest(BaseModel):
    objective: str = Field(min_length=1)


class CaptainPlanRequest(BaseModel):
    instruction: str = Field(min_length=1)


class CaptainQueueItemCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    target_role: Literal["ui_inspector", "safety_auditor", "test_runner", "implementer", "docs_writer", "reviewer"] = "reviewer"
    priority: int = 1
    dependencies: list[str] = Field(default_factory=list)
    file_scope: list[str] = Field(default_factory=list)
    forbidden_file_scope: list[str] = Field(default_factory=list)
    max_attempts: int = 2
    evidence_required: list[str] = Field(default_factory=list)
    export_format: Literal["codex_cli", "agy_cli", "generic_markdown"] = "generic_markdown"
    allowed_files: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)


class CaptainQueueItemStatusRequest(BaseModel):
    status: Literal["queued", "assigned", "evidence_required", "blocked", "completed", "cancelled"]


class CaptainAssignmentEvidenceRequest(BaseModel):
    evidence_summary: str = Field(min_length=1)
    source_ref: Optional[str] = None
    artifact_refs: list[str] = Field(default_factory=list)
    verdict: Literal["unknown", "passed", "failed", "blocked"] = "passed"


class CaptainAssignmentCompleteRequest(BaseModel):
    evidence_summary: str = Field(min_length=1)
    output_summary: Optional[str] = None


class CaptainAssignmentFailRequest(BaseModel):
    reason: Optional[str] = None


STATE_MACHINE_DIR = CAPTAIN_ROOT / "state_machine"


def _state_path(captain_run_id: str) -> Path:
    return STATE_MACHINE_DIR / f"{captain_run_id}.json"


def _safe_captain_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _load_state(captain_run_id: str) -> CaptainState:
    path = _state_path(captain_run_id)
    if not path.exists():
        raise FileNotFoundError(captain_run_id)
    return CaptainState.model_validate_json(path.read_text(encoding="utf-8"))


def _save_state(state: CaptainState) -> CaptainState:
    STATE_MACHINE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(state.captain_run_id).write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return state


def _update_state(captain_run_id: str, updater) -> CaptainState:
    with FILE_LOCK:
        state = _load_state(captain_run_id)
        updated = updater(state)
        updated.updated_at = _now()
        return _save_state(updated)


def _record_transition(state: CaptainState, from_status: str, to_status: str, reason: str) -> CaptainTransition:
    transition = CaptainTransition(
        transition_id=f"transition_{uuid.uuid4().hex[:8]}",
        captain_run_id=state.captain_run_id,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        created_at=_now(),
    )
    state.transitions.append(transition)
    return transition


def _link_workbench_run(state: CaptainState) -> None:
    try:
        WORKBENCH_STORE.get_thread(state.thread_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Workbench thread {state.thread_id} not found.") from exc

    try:
        run = WORKBENCH_STORE.get_run(state.run_id)
    except Exception:
        WORKBENCH_STORE.create_run(
            state.thread_id,
            WorkbenchRunCreateRequest(
                run_id=state.run_id,
                title=f"Captain run: {state.objective}",
                current_step=state.current_step,
                status="queued",
                recovery_hint=None,
            ),
        )
    else:
        run.title = f"Captain run: {state.objective}"
        run.current_step = state.current_step
        run.updated_at = _now()
        WORKBENCH_STORE._save_run(run)


def _append_workbench_event(
    state: CaptainState,
    *,
    event_type: str,
    title: str,
    detail: str,
    severity: str = "info",
) -> None:
    WORKBENCH_STORE.append_run_event(
        state.run_id,
        WorkbenchRunEventCreateRequest(
            event_type=event_type,  # type: ignore[arg-type]
            title=title,
            detail=detail,
            severity=severity,  # type: ignore[arg-type]
        ),
    )


def _render_queue_item_export_text(state: CaptainState, item: PromptQueueItem) -> str:
    thread_title = state.thread_id
    try:
        thread_title = WORKBENCH_STORE.get_thread(state.thread_id).get("title") or state.thread_id
    except Exception:
        pass
    allowed_files = "\n".join(f"- {path}" for path in item.file_scope or item.allowed_files or ["(none)"])
    forbidden_files = "\n".join(f"- {path}" for path in item.forbidden_file_scope or ["_mctable/**", "src-tauri/**"])
    forbidden_actions = "\n".join(f"- {action}" for action in item.forbidden_actions or [
        "Do not commit.",
        "Do not push.",
        "Do not launch real external agents.",
        "Do not execute arbitrary shell commands.",
    ])
    acceptance_checks = "\n".join(f"- {check}" for check in item.acceptance_checks or ["Return honest evidence."])
    evidence_required = "\n".join(f"- {check}" for check in item.evidence_required or ["Return evidence before asking to continue."])
    dependencies = ", ".join(item.dependencies) if item.dependencies else "none"
    export_lines = [
        f"# McHarness Bounded Minion Prompt",
        "",
        "## Session",
        f"- Session title: {thread_title}",
        f"- Session id: {state.thread_id}",
        f"- Captain run id: {state.captain_run_id}",
        f"- Queue item id: {item.queue_item_id}",
        "",
        "## Assignment",
        f"- Queue item title: {item.title}",
        f"- Target role: {item.target_role}",
        f"- Exact goal: {state.objective}",
        "",
        "## Prompt",
        item.prompt,
        "",
        "## Safety constraints",
        "- FAKE WORKER MODE",
        "- REAL AGENT LAUNCH DISABLED",
        "- ARBITRARY COMMAND EXECUTION DISABLED",
        "",
        "## Files or areas to inspect",
        allowed_files,
        "",
        "## Forbidden files",
        forbidden_files,
        "",
        "## Forbidden actions",
        forbidden_actions,
        "",
        "## Acceptance tests",
        acceptance_checks,
        "",
        "## Required evidence",
        evidence_required,
        "",
        "## Dependencies",
        f"- {dependencies}",
        "",
        "## Required final proof format",
        "- summary",
        "- evidence",
        "- status",
        "- exact files inspected or changed",
        "- commands/tests run",
        "- what is proven",
        "- what remains unproven",
        "",
        "Do not commit.",
        "Do not push.",
        "Do not launch real external agents.",
        "Do not execute arbitrary shell commands.",
    ]
    return "\n".join(export_lines)


def _queue_dependencies_complete(state: CaptainState, dependencies: list[str]) -> bool:
    completed = {queued.queue_item_id for queued in state.prompt_queue if queued.status == "completed"}
    return all(dep in completed for dep in dependencies)


def _queue_item_dependency_complete(state: CaptainState, item: PromptQueueItem) -> bool:
    return _queue_dependencies_complete(state, item.dependencies)


def _find_state_by_queue_item_id(queue_item_id: str) -> tuple[CaptainState, PromptQueueItem]:
    STATE_MACHINE_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(STATE_MACHINE_DIR.glob("*.json")):
        try:
            state = CaptainState.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in state.prompt_queue:
            if item.queue_item_id == queue_item_id:
                return state, item
    raise FileNotFoundError(queue_item_id)


def _find_state_by_assignment_id(assignment_id: str) -> tuple[CaptainState, MinionAssignment]:
    STATE_MACHINE_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(STATE_MACHINE_DIR.glob("*.json")):
        try:
            state = CaptainState.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for assignment in state.assignments:
            if assignment.assignment_id == assignment_id:
                return state, assignment
    raise FileNotFoundError(assignment_id)


def _sync_state_status_from_assignments(state: CaptainState) -> None:
    if any(assignment.status == "failed" for assignment in state.assignments):
        state.status = "failed"
        return
    if any(assignment.status == "blocked" for assignment in state.assignments):
        state.status = "blocked_on_gate"
        return
    if state.assignments and all(assignment.status == "completed" for assignment in state.assignments):
        state.status = "completed"
        return
    if any(assignment.status == "evidence_submitted" for assignment in state.assignments):
        state.status = "waiting_for_evidence"
        return
    if state.assignments:
        state.status = "assigning"


def _sync_state_status_from_queue(state: CaptainState) -> None:
    if any(item.status == "blocked" for item in state.prompt_queue):
        state.status = "blocked_on_gate"
        return
    if state.prompt_queue and all(item.status == "completed" for item in state.prompt_queue):
        state.status = "completed"
        return
    if any(item.status in {"assigned", "evidence_required"} for item in state.prompt_queue):
        state.status = "waiting_for_evidence"
        return
    if state.prompt_queue:
        state.status = "queued"


def _generate_plan(state: CaptainState, instruction: str) -> CaptainPlan:
    objective_words = [word.strip(".,:;!?") for word in state.objective.split()[:6] if word.strip(".,:;!?")]
    instruction_words = [word.strip(".,:;!?") for word in instruction.split()[:6] if word.strip(".,:;!?")]
    summary = f"Plan for {state.objective.lower()} based on {instruction.lower()}."
    return CaptainPlan(
        plan_id=f"plan_{uuid.uuid4().hex[:8]}",
        captain_run_id=state.captain_run_id,
        summary=summary,
        assumptions=[
            "Work stays local and supervised.",
            "No real external agent launch occurs.",
        ],
        steps=[
            "Intake the objective and confirm scope.",
            f"Queue bounded work items for {' '.join(objective_words) or 'the objective'}.",
            f"Assign minions and gather evidence for {' '.join(instruction_words) or 'the instruction'}.",
            "Open a human proof gate before continuation.",
        ],
        acceptance_criteria=[
            "Captain state serializes and persists.",
            "Run ledger events are appended for each transition.",
            "Continuation stays blocked until proof gates are approved.",
        ],
        risks=[
            "Human approval is required before continuation.",
            "No real execution path is wired in Captain Mode.",
        ],
        requires_human_gate=True,
        created_at=_now(),
    )


def _generate_queue_items(state: CaptainState, plan: CaptainPlan) -> list[PromptQueueItem]:
    roles = ["reviewer", "test_runner", "docs_writer"]
    files = [
        ["README.md", "docs/architecture.md"],
        ["tests/test_warden_captain.py", "tests/test_warden_workbench.py"],
        ["web/warden/index.html", "docs/workbench_core.md"],
    ]
    prompts = [
        f"Review the captain state machine for {state.objective}.",
        "Collect proof that the run ledger and gate flow stay local-only.",
        "Summarize the proof and update the operator notes.",
    ]
    checks = [
        ["CaptainState persists", "transition recorded"],
        ["proof gate blocks continuation", "no command execution"],
        ["notes remain honest", "runtime artifacts stay ignored"],
    ]
    items: list[PromptQueueItem] = []
    for index, role in enumerate(roles, start=1):
        item = PromptQueueItem(
            queue_item_id=f"queue_{uuid.uuid4().hex[:8]}",
            captain_run_id=state.captain_run_id,
            title=f"Queue item {index}",
            prompt=prompts[index - 1],
            status="queued",
            priority=index,
            target_role=role,  # type: ignore[arg-type]
            dependencies=[items[-1].queue_item_id] if items and index > 1 else [],
            file_scope=files[index - 1],
            forbidden_file_scope=["_mctable/**", "src-tauri/**"],
            max_attempts=2,
            attempt_count=0,
            evidence_required=list(checks[index - 1]),
            export_format="generic_markdown",
            export_text="",
            allowed_files=files[index - 1],
            forbidden_actions=[
                "arbitrary shell execution",
                "real external agent launch",
                "public worker launch",
            ],
            acceptance_checks=checks[index - 1],
            created_at=_now(),
            updated_at=_now(),
        )
        item.export_text = _render_queue_item_export_text(state, item)
        items.append(
            item
        )
    return items


def _generate_assignments(state: CaptainState) -> list[MinionAssignment]:
    assignments: list[MinionAssignment] = []
    for queue_item in state.prompt_queue:
        dependency_blocked = not _queue_item_dependency_complete(state, queue_item)
        assignments.append(
            MinionAssignment(
                assignment_id=f"assign_{uuid.uuid4().hex[:8]}",
                captain_run_id=state.captain_run_id,
                queue_item_id=queue_item.queue_item_id,
                role=queue_item.target_role,
                title=queue_item.title,
                instructions=queue_item.prompt,
                status="blocked" if dependency_blocked else "assigned",
                may_edit=queue_item.target_role in {"reviewer", "docs_writer"},
                may_commit=False,
                may_execute_shell=False,
                must_return_evidence=True,
                handoff_prompt=queue_item.export_text,
                evidence_required=list(queue_item.acceptance_checks),
                created_at=_now(),
                updated_at=_now(),
            )
        )
    return assignments


def _state_has_open_gate(state: CaptainState) -> bool:
    try:
        run = WORKBENCH_STORE.get_run(state.run_id)
    except Exception:
        return False
    return any(gate.status == "open" for gate in run.proof_gates)


def _state_has_blocking_gate(state: CaptainState) -> bool:
    try:
        run = WORKBENCH_STORE.get_run(state.run_id)
    except Exception:
        return False
    return any(gate.status in {"open", "rejected", "blocked"} for gate in run.proof_gates)


def _state_view(state: CaptainState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def _safe_gate(reason: str, triggered_by: str = "captain") -> HardGate:
    return HardGate(
        gate_id=f"gate_{uuid.uuid4().hex[:8]}",
        kind="safety",
        reason=reason,
        triggered_by=triggered_by,
        blocked=True,
        created_at=_now(),
    )


def _template_library() -> dict[str, CaptainTemplate]:
    return {
        "release_qa": CaptainTemplate(
            template_id="release_qa",
            title="Release QA",
            objective="Verify the release candidate and collect proof.",
            prompt_queue=[
                WorkflowPromptQueueItem(
                    prompt_id="review_status",
                    title="Review backend status and capabilities",
                    notes="Check the local API, worker runner, and cockpit target wording.",
                ),
                WorkflowPromptQueueItem(
                    prompt_id="compile_report",
                    title="Compile the release report",
                    notes="Summarize what was proven and what remains unproven.",
                ),
            ],
            minion_tasks=[
                MinionTask(
                    minion_id="status_auditor",
                    role="auditor",
                    scope="Review the live status and proof surface.",
                    files=["src/warden/api.py", "web/warden/index.html"],
                    notes="Keep the scope to the local desktop surface.",
                ),
                MinionTask(
                    minion_id="report_writer",
                    role="scribe",
                    scope="Draft the final report and proof summary.",
                    files=["docs/release_checklist.md", "docs/demo_script.md"],
                    notes="Use only verified backend results.",
                ),
            ],
            hard_gates=[
                _safe_gate("Keep the work local, scoped, and free of runtime artifacts."),
            ],
            scoped_commit_plan=ScopedCommitPlan(
                commit_message="docs(marius-desktop): prepare release proof",
                files=["docs/release_checklist.md", "docs/demo_script.md"],
            ),
            planned_acceptance_commands=[
                "python -m pytest -q tests/test_warden_captain.py tests/test_warden_api.py",
                "PYTHONPATH=. python pytest -q tests/test_warden_api.py",
            ],
        ),
        "ui_polish": CaptainTemplate(
            template_id="ui_polish",
            title="UI Polish",
            objective="Tune cockpit wording and status presentation.",
            prompt_queue=[
                WorkflowPromptQueueItem(
                    prompt_id="check_status_strip",
                    title="Check the status strip wording",
                    notes="Use the live backend target and current service state.",
                ),
                WorkflowPromptQueueItem(
                    prompt_id="review_shell",
                    title="Review the desktop shell copy",
                    notes="Keep the wrapper honest and local-only.",
                ),
            ],
            minion_tasks=[
                MinionTask(
                    minion_id="cockpit_editor",
                    role="designer",
                    scope="Polish the cockpit display text.",
                    files=["web/warden/index.html"],
                ),
                MinionTask(
                    minion_id="shell_editor",
                    role="designer",
                    scope="Polish the desktop shell display text.",
                    files=["src-tauri/frontend/index.html"],
                ),
            ],
            hard_gates=[_safe_gate("Keep the work local and avoid runtime artifacts.")],
            planned_acceptance_commands=[
                "python -m pytest -q tests/test_warden_cockpit_static.py tests/test_warden_tauri_shell.py",
            ],
        ),
        "docs_audit": CaptainTemplate(
            template_id="docs_audit",
            title="Docs Audit",
            objective="Cross-check the public docs against verified backend behavior.",
            prompt_queue=[
                WorkflowPromptQueueItem(
                    prompt_id="compare_docs",
                    title="Compare docs and live behavior",
                    notes="Confirm that the docs match the verified API and shell behavior.",
                ),
                WorkflowPromptQueueItem(
                    prompt_id="note_gaps",
                    title="Record honest gaps",
                    notes="List the remaining unproven items without overstating them.",
                ),
            ],
            minion_tasks=[
                MinionTask(
                    minion_id="doc_checker",
                    role="auditor",
                    scope="Audit the release docs for accuracy.",
                    files=["docs/architecture.md", "docs/demo_script.md", "docs/marius_agent_desktop_captain_mode.md"],
                ),
            ],
            hard_gates=[_safe_gate("Keep the audit read-only and local.")],
            scoped_commit_plan=ScopedCommitPlan(
                commit_message="docs(marius-desktop): audit release copy",
                files=["docs/architecture.md", "docs/demo_script.md", "docs/marius_agent_desktop_captain_mode.md"],
            ),
            planned_acceptance_commands=[
                "python -m pytest -q tests/test_warden_api.py tests/test_warden_captain.py",
            ],
        ),
        "test_triage": CaptainTemplate(
            template_id="test_triage",
            title="Test Triage",
            objective="Separate passing checks from failing checks and record the delta.",
            prompt_queue=[
                WorkflowPromptQueueItem(
                    prompt_id="run_focus",
                    title="Run the focused acceptance set",
                    notes="Use the smallest test slice that proves the change.",
                ),
                WorkflowPromptQueueItem(
                    prompt_id="record_delta",
                    title="Record the test delta",
                    notes="Capture only verified failures and fixes.",
                ),
            ],
            minion_tasks=[
                MinionTask(
                    minion_id="test_runner",
                    role="qa",
                    scope="Run the focused backend tests.",
                    files=["tests/test_warden_api.py", "tests/test_warden_captain.py"],
                ),
            ],
            hard_gates=[_safe_gate("Do not widen scope beyond the local test slice.")],
            planned_acceptance_commands=[
                "python -m pytest -q tests/test_warden_captain.py tests/test_warden_api.py tests/test_warden_contracts.py tests/test_warden_graph.py",
            ],
        ),
        "marathon_queue": CaptainTemplate(
            template_id="marathon_queue",
            title="Marathon Queue",
            objective="Prepare the next prompt queue for a long local sprint.",
            prompt_queue=[
                WorkflowPromptQueueItem(
                    prompt_id="load_queue",
                    title="Load the next queue item",
                    notes="Work one prompt at a time and keep the scope narrow.",
                ),
                WorkflowPromptQueueItem(
                    prompt_id="verify_commit",
                    title="Verify the scoped commit",
                    notes="Stage only the allowed files and confirm the tree is clean.",
                ),
            ],
            minion_tasks=[
                MinionTask(
                    minion_id="queue_keeper",
                    role="coordinator",
                    scope="Track prompt order and commit boundaries.",
                    files=["docs/marius_agent_desktop_captain_mode.md", "docs/architecture.md"],
                ),
            ],
            hard_gates=[_safe_gate("Keep the sprint local and avoid runtime artifacts.")],
            planned_acceptance_commands=[
                "python -m pytest -q tests/test_warden_captain.py",
                "ruff check src/warden tests/test_warden_* scripts/fake_worker.py pytest -q tests/test_warden_api.py ",
            ],
        ),
    }


CAPTAIN_TEMPLATES = _template_library()


def _template_text_fields(template: CaptainTemplate) -> list[str]:
    values: list[str] = [
        template.template_id,
        template.title,
        template.objective,
        template.notes or "",
    ]
    for item in template.prompt_queue:
        values.extend([item.prompt_id, item.title, item.prompt_path or "", item.commit_message or "", item.notes or ""])
    for task in template.minion_tasks:
        values.extend([task.minion_id, task.role or "", task.scope, task.notes or ""])
        values.extend(task.files)
    for gate in template.hard_gates:
        values.extend([gate.gate_id, gate.kind, gate.reason, gate.triggered_by])
    if template.scoped_commit_plan:
        values.extend(
            [
                template.scoped_commit_plan.commit_message,
                template.scoped_commit_plan.notes or "",
            ]
        )
        values.extend(template.scoped_commit_plan.files)
    values.extend(template.planned_acceptance_commands)
    return [value for value in values if value]


def _reject_forbidden_template_content(template: CaptainTemplate) -> None:
    blocked_phrases = [
        "shell=true",
        "dangerously-skip-permissions",
        "--yolo",
        "--always-approve",
        "public worker launch",
        "real external agent launch",
        "rm -rf",
        "deploy",
        "secret",
        "credential",
        "password",
        "token",
        "grok",
        "codex",
        "claude",
        "agy",
    ]
    for text in _template_text_fields(template):
        lowered = text.lower()
        for phrase in blocked_phrases:
            if phrase in lowered:
                raise HTTPException(
                    status_code=400,
                    detail=f"Template content is not allowed: '{phrase}'",
                )


@router.get("/runs", response_model=list[CaptainRun])
def list_captain_runs() -> list[CaptainRun]:
    _ensure_dirs()
    runs: list[CaptainRun] = []
    for path in sorted(RUNS_DIR.glob("*.json")):
        try:
            runs.append(CaptainRun.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return runs


@router.get("/templates", response_model=list[CaptainTemplate])
def list_captain_templates() -> list[CaptainTemplate]:
    return [template.model_copy(deep=True) for template in CAPTAIN_TEMPLATES.values()]


@router.get("/templates/{template_id}", response_model=CaptainTemplate)
def get_captain_template(template_id: str) -> CaptainTemplate:
    try:
        return CAPTAIN_TEMPLATES[template_id].model_copy(deep=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Captain template {template_id} not found.") from exc


@router.post("/runs/from-template", response_model=CaptainRun)
def create_captain_run_from_template(req: CaptainTemplateRunRequest) -> CaptainRun:
    if req.command_execution_request:
        raise HTTPException(
            status_code=501,
            detail="not_implemented: command execution is blocked; Captain Mode stores planned acceptance commands as text only.",
        )

    _reject_forbidden_template_content(req.template)
    template = req.template.model_copy(deep=True)
    now = _now()
    run = CaptainRun(
        run_id=f"run_{uuid.uuid4().hex[:8]}",
        objective=template.objective,
        status="active",
        prompt_queue=template.prompt_queue,
        minion_tasks=template.minion_tasks,
        evidence_records=[],
        hard_gates=template.hard_gates,
        scoped_commit_plan=template.scoped_commit_plan,
        next_action=req.next_action,
        planned_acceptance_commands=template.planned_acceptance_commands,
        created_at=now,
        updated_at=now,
    )
    return _save_run(run)


@router.post("/runs", response_model=CaptainRun)
def create_captain_run(req: CaptainRunCreateRequest) -> CaptainRun:
    now = _now()
    run = CaptainRun(
        run_id=f"run_{uuid.uuid4().hex[:8]}",
        objective=req.objective,
        status="active",
        prompt_queue=req.prompt_queue,
        minion_tasks=req.minion_tasks,
        evidence_records=req.evidence_records,
        hard_gates=req.hard_gates,
        scoped_commit_plan=req.scoped_commit_plan,
        next_action=req.next_action,
        planned_acceptance_commands=req.planned_acceptance_commands,
        created_at=now,
        updated_at=now,
    )
    return _save_run(run)


@router.get("/runs/{run_id}", response_model=dict[str, Any])
def get_captain_run(run_id: str) -> dict[str, Any]:
    try:
        if _state_path(run_id).exists():
            return _state_view(_load_state(run_id))
        return _load_run(run_id).model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {run_id} not found.") from exc


@router.post("/runs/{run_id}/evidence", response_model=CaptainRun)
def add_evidence(run_id: str, req: EvidenceCreateRequest) -> CaptainRun:
    def _append(run: CaptainRun) -> CaptainRun:
        run.evidence_records.append(
            EvidenceRecord(
                evidence_id=f"ev_{uuid.uuid4().hex[:8]}",
                kind=req.kind,
                summary=req.summary,
                status=req.status,
                command_text=req.command_text,
                details=req.details,
                captured_by=req.captured_by,
                artifacts=req.artifacts,
                captured_at=_now(),
            )
        )
        return run

    try:
        return _update_run(run_id, _append)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {run_id} not found.") from exc


@router.post("/runs/{run_id}/gate", response_model=CaptainRun)
def add_gate(run_id: str, req: GateCreateRequest) -> CaptainRun:
    def _block(run: CaptainRun) -> CaptainRun:
        run.hard_gates.append(
            HardGate(
                gate_id=f"gate_{uuid.uuid4().hex[:8]}",
                kind=req.kind,
                reason=req.reason,
                triggered_by=req.triggered_by,
                blocked=True,
                created_at=_now(),
            )
        )
        run.status = "blocked"
        return run

    try:
        return _update_run(run_id, _block)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {run_id} not found.") from exc


@router.post("/runs/{run_id}/gates/{gate_id}/decision", response_model=CaptainRun)
def record_gate_decision(run_id: str, gate_id: str, req: GateDecisionRequest) -> CaptainRun:
    def _record(run: CaptainRun) -> CaptainRun:
        gate = next((item for item in run.hard_gates if item.gate_id == gate_id), None)
        if gate is None:
            raise HTTPException(status_code=404, detail=f"Captain gate {gate_id} not found.")
        gate.decision = req.decision
        gate.decision_actor = req.actor
        gate.decision_note = req.reviewer_note
        gate.decided_at = _now()
        return run

    try:
        return _update_run(run_id, _record)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {run_id} not found.") from exc


@router.post("/runs/{run_id}/next", response_model=CaptainRun)
def set_next_action(run_id: str, req: CaptainNextRequest) -> CaptainRun:
    if req.command_execution_request:
        raise HTTPException(
            status_code=501,
            detail="not_implemented: command execution is blocked; Captain Mode stores planned acceptance commands as text only.",
        )

    def _advance(run: CaptainRun) -> CaptainRun:
        if run.hard_gates:
            raise HTTPException(status_code=409, detail="Continuation blocked by hard gate.")
        run.next_action = req.next_action
        run.planned_acceptance_commands = req.planned_acceptance_commands
        return run

    try:
        return _update_run(run_id, _advance)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {run_id} not found.") from exc


@router.get("/state-machine")
def get_captain_state_machine() -> dict[str, Any]:
    return {
        "schema": "mcharness.captain.v0.2",
        "local_only": True,
        "fake_worker_only": True,
        "real_external_agent_launch_disabled": True,
        "public_worker_launch_disabled": True,
        "arbitrary_shell_execution_disabled": True,
        "workflow": [
            "operator_instruction",
            "captain_intake",
            "plan",
            "prompt_queue",
            "bounded_minion_assignments",
            "evidence_requirements",
            "proof_gates",
            "human_decision",
            "blocked_or_safe_noop_continuation",
        ],
        "statuses": [
            "intake",
            "planning",
            "queued",
            "assigning",
            "waiting_for_evidence",
            "blocked_on_gate",
            "ready_to_continue",
            "completed",
            "failed",
            "cancelled",
        ],
    }


def create_captain_state_machine_run(thread_id: str, objective: str) -> CaptainState:
    captain_run_id = _safe_captain_id("captain")
    now = _now()
    state = CaptainState(
        captain_run_id=captain_run_id,
        thread_id=thread_id,
        run_id=captain_run_id,
        status="intake",
        objective=objective,
        current_step="intake",
        created_at=now,
        updated_at=now,
    )
    _link_workbench_run(state)
    _record_transition(state, "created", "intake", "Captain intake created from a workbench thread.")
    _append_workbench_event(
        state,
        event_type="note",
        title="Captain intake",
        detail=f"Objective: {objective}",
        severity="info",
    )
    return _save_state(state)


@router.post("/runs/{captain_run_id}/plan", response_model=CaptainState)
def plan_captain_run(captain_run_id: str, req: CaptainPlanRequest) -> CaptainState:
    def _plan(state: CaptainState) -> CaptainState:
        before = state.status
        state.plan = _generate_plan(state, req.instruction)
        state.current_step = "plan"
        state.status = "planning"
        _record_transition(state, before, state.status, f"Planned from instruction: {req.instruction}")
        _append_workbench_event(
            state,
            event_type="plan",
            title="Captain plan",
            detail=state.plan.summary,
            severity="info",
        )
        try:
            run = WORKBENCH_STORE.get_run(state.run_id)
            run.current_step = state.current_step
            run.updated_at = _now()
            WORKBENCH_STORE._save_run(run)
        except Exception:
            pass
        return state

    try:
        return _update_state(captain_run_id, _plan)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.post("/runs/{captain_run_id}/queue", response_model=CaptainState)
def queue_captain_run(captain_run_id: str) -> CaptainState:
    def _queue(state: CaptainState) -> CaptainState:
        if state.plan is None:
            raise HTTPException(status_code=409, detail="Captain plan is required before queue generation.")
        before = state.status
        if not state.prompt_queue:
            state.prompt_queue = _generate_queue_items(state, state.plan)
        state.current_step = "queue"
        state.status = "queued"
        _record_transition(state, before, state.status, "Generated bounded prompt queue items.")
        for item in state.prompt_queue:
            _append_workbench_event(
                state,
                event_type="note",
                title=item.title,
                detail=f"{item.prompt} Acceptance checks: {', '.join(item.acceptance_checks)}.",
                severity="info",
            )
        if state.plan.requires_human_gate:
            gate = WORKBENCH_STORE.open_run_proof_gate(
                state.run_id,
                WorkbenchRunProofGateCreateRequest(
                    title="Captain human approval",
                    reason="Captain plan requires human approval before continuation.",
                    requires_human=True,
                ),
            )
            state.proof_gate_id = gate.gate_id
            before_gate = state.status
            state.status = "blocked_on_gate"
            _record_transition(state, before_gate, state.status, "Opened a human proof gate.")
            _append_workbench_event(
                state,
                event_type="proof_gate",
                title=gate.title,
                detail=gate.reason,
                severity="blocked",
            )
        try:
            run = WORKBENCH_STORE.get_run(state.run_id)
            run.current_step = state.current_step
            run.updated_at = _now()
            WORKBENCH_STORE._save_run(run)
        except Exception:
            pass
        return state

    try:
        return _update_state(captain_run_id, _queue)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.get("/runs/{captain_run_id}/queue", response_model=list[PromptQueueItem])
def get_captain_queue(captain_run_id: str) -> list[PromptQueueItem]:
    try:
        return _load_state(captain_run_id).prompt_queue
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.post("/runs/{captain_run_id}/assign-minions", response_model=CaptainState)
def assign_captain_minions(captain_run_id: str) -> CaptainState:
    def _assign(state: CaptainState) -> CaptainState:
        if not state.prompt_queue:
            raise HTTPException(status_code=409, detail="Prompt queue is required before minion assignment.")
        before = state.status
        if not state.assignments:
            state.assignments = _generate_assignments(state)
        state.current_step = "assign"
        for assignment in state.assignments:
            queue_item = next((item for item in state.prompt_queue if item.queue_item_id == assignment.queue_item_id), None)
            if queue_item is not None and queue_item.status != "completed" and not _queue_dependencies_complete(state, list(queue_item.dependencies)):
                assignment.status = "blocked"
                queue_item.status = "blocked"
                queue_item.updated_at = _now()
        _sync_state_status_from_assignments(state)
        if _state_has_open_gate(state):
            state.status = "blocked_on_gate"
        _record_transition(state, before, state.status, "Created bounded minion assignments.")
        for assignment in state.assignments:
            _append_workbench_event(
                state,
                event_type="minion_assignment",
                title=assignment.title,
                detail=f"{assignment.role}: {assignment.instructions}",
                severity="info",
            )
        try:
            run = WORKBENCH_STORE.get_run(state.run_id)
            run.current_step = state.current_step
            run.updated_at = _now()
            WORKBENCH_STORE._save_run(run)
        except Exception:
            pass
        return state

    try:
        return _update_state(captain_run_id, _assign)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.get("/runs/{captain_run_id}/assignments", response_model=list[MinionAssignment])
def get_captain_assignments(captain_run_id: str) -> list[MinionAssignment]:
    try:
        return _load_state(captain_run_id).assignments
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.post("/runs/{captain_run_id}/continue")
def continue_captain_run(captain_run_id: str) -> dict[str, Any]:
    def _continue(state: CaptainState) -> dict[str, Any]:
        if _state_has_open_gate(state):
            before = state.status
            state.status = "blocked_on_gate"
            _record_transition(state, before, state.status, "Continuation blocked by open proof gates.")
            _append_workbench_event(
                state,
                event_type="blocked",
                title="Continuation blocked",
                detail="Approve/reject the open proof gates before continuing.",
                severity="blocked",
            )
            return {
                "status": "blocked",
                "reason": "Open proof gates block continuation.",
                "recovery_hint": "Approve/reject the open proof gates before continuing.",
                "state": _state_view(state),
            }
        if _state_has_blocking_gate(state):
            before = state.status
            state.status = "blocked_on_gate"
            _record_transition(state, before, state.status, "Rejected or edit-requested proof gates block continuation.")
            _append_workbench_event(
                state,
                event_type="blocked",
                title="Continuation blocked",
                detail="Resolve the rejected or edit-requested proof gates before continuing.",
                severity="blocked",
            )
            return {
                "status": "blocked",
                "reason": "Rejected or edit-requested proof gates block continuation.",
                "recovery_hint": "Resolve the proof gates before continuing.",
                "state": _state_view(state),
            }
        before = state.status
        if state.prompt_queue or state.assignments or state.plan:
            state.status = "ready_to_continue"
            reason = "Captain plan and proof gates are ready; no execution will occur."
            status = "ready_to_continue"
        else:
            state.status = "queued"
            reason = "Continuation is not wired to real execution in the public RC."
            status = "safe_noop"
        _record_transition(state, before, state.status, reason)
        _append_workbench_event(
            state,
            event_type="note",
            title="Safe noop",
            detail=reason,
            severity="info",
        )
        return {
            "status": status,
            "reason": reason,
            "recovery_hint": "Use fake-worker-only tasks or record manual evidence.",
            "state": _state_view(state),
        }

    try:
        with FILE_LOCK:
            state = _load_state(captain_run_id)
            payload = _continue(state)
            state.updated_at = _now()
            _save_state(state)
            return payload
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.get("/runs/{captain_run_id}/transitions", response_model=list[CaptainTransition])
def get_captain_transitions(captain_run_id: str) -> list[CaptainTransition]:
    try:
        return _load_state(captain_run_id).transitions
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.post("/runs/{captain_run_id}/queue/items", response_model=CaptainState)
def add_captain_queue_item(captain_run_id: str, req: CaptainQueueItemCreateRequest) -> CaptainState:
    def _add(state: CaptainState) -> CaptainState:
        before = state.status
        dependency_blocked = bool(req.dependencies) and not _queue_dependencies_complete(state, list(req.dependencies))
        item = PromptQueueItem(
            queue_item_id=f"queue_{uuid.uuid4().hex[:8]}",
            captain_run_id=state.captain_run_id,
            title=req.title,
            prompt=req.prompt,
            status="blocked" if dependency_blocked else "queued",
            priority=req.priority,
            target_role=req.target_role,
            dependencies=list(req.dependencies),
            file_scope=list(req.file_scope),
            forbidden_file_scope=list(req.forbidden_file_scope),
            max_attempts=req.max_attempts,
            attempt_count=0,
            evidence_required=list(req.evidence_required),
            export_format=req.export_format,
            export_text="",
            allowed_files=list(req.file_scope or req.allowed_files),
            forbidden_actions=list(req.forbidden_actions),
            acceptance_checks=list(req.acceptance_checks),
            created_at=_now(),
            updated_at=_now(),
        )
        item.export_text = _render_queue_item_export_text(state, item)
        state.prompt_queue.append(item)
        _record_transition(state, before, state.status, f"Added prompt queue item: {item.title}")
        _append_workbench_event(
            state,
            event_type="note",
            title=item.title,
            detail=f"Queue item added with {len(item.evidence_required)} evidence checks.",
            severity="info",
        )
        return state

    try:
        return _update_state(captain_run_id, _add)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.post("/queue/{queue_item_id}/status", response_model=CaptainState)
def update_captain_queue_item_status(queue_item_id: str, req: CaptainQueueItemStatusRequest) -> CaptainState:
    try:
        state, item = _find_state_by_queue_item_id(queue_item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain queue item {queue_item_id} not found.") from exc

    def _update(found: CaptainState) -> CaptainState:
        before = found.status
        target = next((queued for queued in found.prompt_queue if queued.queue_item_id == queue_item_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Captain queue item {queue_item_id} not found.")
        target.status = req.status
        target.updated_at = _now()
        if req.status == "completed":
            target.attempt_count = min(target.max_attempts, target.attempt_count + 1)
        _sync_state_status_from_assignments(found)
        _record_transition(found, before, found.status, f"Queue item {queue_item_id} updated to {req.status}.")
        return found

    try:
        return _update_state(state.captain_run_id, _update)
    except HTTPException:
        raise


@router.post("/queue/{queue_item_id}/export", response_class=PlainTextResponse)
def export_captain_queue_item(queue_item_id: str) -> str:
    try:
        state, item = _find_state_by_queue_item_id(queue_item_id)
        return item.export_text or _render_queue_item_export_text(state, item)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain queue item {queue_item_id} not found.") from exc


@router.post("/runs/{captain_run_id}/assignments/{assignment_id}/evidence", response_model=CaptainState)
def record_captain_assignment_evidence(
    captain_run_id: str,
    assignment_id: str,
    req: CaptainAssignmentEvidenceRequest,
) -> CaptainState:
    def _evidence(state: CaptainState) -> CaptainState:
        assignment = next((item for item in state.assignments if item.assignment_id == assignment_id), None)
        if assignment is None:
            raise HTTPException(status_code=404, detail=f"Captain assignment {assignment_id} not found.")
        if assignment.captain_run_id != captain_run_id:
            raise HTTPException(status_code=404, detail=f"Captain assignment {assignment_id} not found.")
        if assignment.status == "blocked":
            raise HTTPException(status_code=409, detail="Blocked assignments cannot receive evidence.")
        if assignment.status == "assigned":
            assignment.status = "waiting_for_result"
        assignment.output_summary = req.evidence_summary
        assignment.status = "evidence_submitted"
        assignment.updated_at = _now()
        queue_item = next((item for item in state.prompt_queue if item.queue_item_id == assignment.queue_item_id), None)
        if queue_item is not None:
            queue_item.attempt_count = min(queue_item.max_attempts, queue_item.attempt_count + 1)
            queue_item.status = "evidence_required"
            queue_item.updated_at = _now()
        _append_workbench_event(
            state,
            event_type="evidence",
            title=assignment.title,
            detail=req.evidence_summary,
            severity="success" if req.verdict == "passed" else "warning" if req.verdict == "unknown" else "error" if req.verdict == "failed" else "blocked",
        )
        try:
            WORKBENCH_STORE.add_run_evidence(
                state.run_id,
                WorkbenchEvidenceRecordCreateRequest(
                    title=assignment.title,
                    summary=req.evidence_summary,
                    source_type="manual",
                    source_ref=req.source_ref,
                    verdict=req.verdict,
                    evidence_id=None,
                ),
            )
        except Exception:
            pass
        _sync_state_status_from_assignments(state)
        _record_transition(state, "waiting_for_result", assignment.status, "Recorded assignment evidence.")
        return state

    try:
        return _update_state(captain_run_id, _evidence)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.post("/runs/{captain_run_id}/assignments/{assignment_id}/complete", response_model=CaptainState)
def complete_captain_assignment(
    captain_run_id: str,
    assignment_id: str,
    req: CaptainAssignmentCompleteRequest,
) -> CaptainState:
    def _complete(state: CaptainState) -> CaptainState:
        assignment = next((item for item in state.assignments if item.assignment_id == assignment_id), None)
        if assignment is None or assignment.captain_run_id != captain_run_id:
            raise HTTPException(status_code=404, detail=f"Captain assignment {assignment_id} not found.")
        if assignment.must_return_evidence and assignment.status != "evidence_submitted":
            raise HTTPException(status_code=409, detail="Evidence is required before completion.")
        assignment.output_summary = req.output_summary or req.evidence_summary
        assignment.status = "completed"
        assignment.updated_at = _now()
        queue_item = next((item for item in state.prompt_queue if item.queue_item_id == assignment.queue_item_id), None)
        if queue_item is not None:
            queue_item.status = "completed"
            queue_item.attempt_count = min(queue_item.max_attempts, queue_item.attempt_count + 1)
            queue_item.updated_at = _now()
        _append_workbench_event(
            state,
            event_type="approval",
            title=assignment.title,
            detail=req.evidence_summary,
            severity="success",
        )
        try:
            WORKBENCH_STORE.add_run_evidence(
                state.run_id,
                WorkbenchEvidenceRecordCreateRequest(
                    title=assignment.title,
                    summary=req.evidence_summary,
                    source_type="manual",
                    source_ref=None,
                    verdict="passed",
                    evidence_id=None,
                ),
            )
        except Exception:
            pass
        _sync_state_status_from_assignments(state)
        if state.status != "completed":
            state.status = "completed" if all(item.status == "completed" for item in state.assignments) else state.status
        _record_transition(state, "evidence_submitted", state.status, "Assignment completed with evidence.")
        return state

    try:
        return _update_state(captain_run_id, _complete)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc


@router.post("/runs/{captain_run_id}/assignments/{assignment_id}/fail", response_model=CaptainState)
def fail_captain_assignment(
    captain_run_id: str,
    assignment_id: str,
    req: CaptainAssignmentFailRequest,
) -> CaptainState:
    def _fail(state: CaptainState) -> CaptainState:
        assignment = next((item for item in state.assignments if item.assignment_id == assignment_id), None)
        if assignment is None or assignment.captain_run_id != captain_run_id:
            raise HTTPException(status_code=404, detail=f"Captain assignment {assignment_id} not found.")
        assignment.status = "failed"
        assignment.output_summary = req.reason or "Assignment failed."
        assignment.updated_at = _now()
        queue_item = next((item for item in state.prompt_queue if item.queue_item_id == assignment.queue_item_id), None)
        if queue_item is not None:
            queue_item.status = "blocked"
            queue_item.updated_at = _now()
        _append_workbench_event(
            state,
            event_type="blocked",
            title=assignment.title,
            detail=req.reason or "Assignment failed.",
            severity="error",
        )
        try:
            WORKBENCH_STORE.append_run_event(
                state.run_id,
                WorkbenchRunEventCreateRequest(
                    event_type="blocked",
                    title=assignment.title,
                    detail=req.reason or "Assignment failed.",
                    severity="error",
                ),
            )
        except Exception:
            pass
        state.status = "failed"
        _record_transition(state, "assigned", state.status, "Assignment failed.")
        return state

    try:
        return _update_state(captain_run_id, _fail)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Captain run {captain_run_id} not found.") from exc
