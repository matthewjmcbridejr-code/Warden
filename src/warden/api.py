import json
import os
import hashlib
import subprocess
import uuid
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen

from .captain import (
    router as captain_router,
    CaptainAssignmentCompleteRequest,
    CaptainAssignmentEvidenceRequest,
    CaptainPlanRequest,
    CaptainQueueItemCreateRequest,
    add_captain_queue_item,
    assign_captain_minions,
    complete_captain_assignment,
    continue_captain_run,
    create_captain_state_machine_run,
    export_captain_queue_item,
    plan_captain_run,
    queue_captain_run,
    record_captain_assignment_evidence,
)
from .contracts import CapabilityStatus, TaskState, WorkerRun
from .graph import (
    CHECKPOINT_DB_PATH,
    LANGGRAPH_AVAILABLE,
    McTableTaskGraph,
    TASKS_DIR,
    checkpoint_file_exists,
    get_runtime_capabilities,
)
from .workbench import (
    router as workbench_router,
    STORE as WORKBENCH_STORE,
    WorkbenchArtifactCreateRequest,
    WorkbenchEvidenceRecordCreateRequest,
    WorkbenchMemoryCreateRequest,
    WorkbenchMemoryRememberRequest,
    WorkbenchRunEventCreateRequest,
    WorkbenchRunProofGateDecisionRequest,
    WorkbenchThreadCreateRequest,
    WorkbenchThreadUpdateRequest,
)
from .worker import WorkerStub, ALLOWED_COMMANDS
from .captain_plans import (
    complete_step as complete_captain_plan_step,
    get_plan_detail,
    get_plan_record,
    list_recent_plans,
    mark_step_dispatched,
    persist_plan,
    revise_step as revise_captain_plan_step,
    sanitize_plan_public,
    stop_plan as stop_captain_plan,
)
from .run_history import (
    create_evidence_record,
    create_run_record,
    evidence_summaries_for_run,
    find_run_by_session,
    get_evidence_record,
    get_run_record,
    list_recent_evidence,
    list_recent_runs,
    update_run_record,
)
from .worklog import EVENT_LABELS, list_recent_worklog
from .mission_control import (
    adjust_mission_plan,
    build_agents_health_items,
    build_mission_control_snapshot,
    build_safety_payload,
    pause_mission,
)
from .runner_sessions import (
    assert_runner_session_capacity,
    build_runner_session_inventory,
    cleanup_runner_sessions,
)
from .proof_gates import (
    assert_step_completion_allowed,
    create_proof_gate,
    decide_proof_gate,
    gate_status_summary_for_run,
    gate_ui_label,
    get_proof_gate,
    list_gates_for_run,
    list_recent_gates,
)
from .run_reports import build_run_report_payload
from .agent_registry import (
    BUILTIN_CODEX_ID,
    McHarnessAgentConfigPatchRequest,
    McHarnessAgentCreateRequest,
    McHarnessAgentPatchRequest,
    McHarnessAgentTestConfigRequest,
    agent_status_payload,
    agent_templates,
    create_registered_agent,
    delete_registered_agent,
    get_agent_by_id,
    list_all_agents,
    probe_agent,
    refresh_agent_statuses,
    sanitize_agent_profile,
    test_agent_config,
    update_registered_agent,
    update_registered_agent_config,
)

router = APIRouter(prefix="/api/marius", tags=["marius-desktop"])
router.include_router(captain_router)
router.include_router(workbench_router)

from .projects import router as projects_router

mcharness_router = APIRouter(prefix="/api/mcharness", tags=["mcharness"])
mcharness_router.include_router(projects_router)
legacy_router = APIRouter(tags=["marius-desktop-legacy"])

SAFE_REPO_PATHS = [
    Path.home() / "workspaces" / "marius-core" / "hybrid-agent-os",
    Path.home() / "workspaces" / "warden" / "mcharness-public-export",
    Path(__file__).resolve().parents[2], # The current repo
]
MCTABLE_ROOT = Path(os.getenv("MCHARNESS_DATA_ROOT", "_mctable"))
ARTIFACT_BODY_ROOT = MCTABLE_ROOT / "mcharness" / "artifacts"
CAPTAIN_PLAN_ROOT = MCTABLE_ROOT / "captain" / "plans"
REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LANES = [
    {
        "lane_id": "codex_cli",
        "title": "Codex CLI",
        "implemented": True,
        "manual_only": True,
    },
    {
        "lane_id": "agy_cli",
        "title": "AGY / Antigravity CLI",
        "implemented": True,
        "manual_only": True,
    },
    {
        "lane_id": "manual_paste",
        "title": "Manual paste-back",
        "implemented": True,
        "manual_only": True,
    },
    {
        "lane_id": "grok_placeholder",
        "title": "Grok",
        "implemented": False,
        "manual_only": True,
    },
    {
        "lane_id": "jules_placeholder",
        "title": "Jules",
        "implemented": False,
        "manual_only": True,
    },
    {
        "lane_id": "opencode_placeholder",
        "title": "OpenCode",
        "implemented": False,
        "manual_only": True,
    },
    {
        "lane_id": "fake_test_lane",
        "title": "Fake Test Lane (internal/harmless for automated proof only)",
        "implemented": True,
        "manual_only": False,
        "test_only": True,
    },
]


def _env_flag(*names: str, default: str = "false") -> bool:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return default.strip().lower() in {"1", "true", "yes", "on"}


def _git_commit() -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    commit = proc.stdout.strip()
    return commit or None


def _public_write_enabled() -> bool:
    return _env_flag("MCHARNESS_PUBLIC_WRITE_ENABLED", "MCHARNESSS_PUBLIC_WRITE_ENABLED", default="true")


def _tmux_runner_enabled() -> bool:
    # Tolerate the common misspelling variant as done for PUBLIC_WRITE
    return _env_flag(
        "MCHARNESS_TMUX_RUNNER_ENABLED",
        "MCHARNESSS_TMUX_RUNNER_ENABLED",
        default="false",
    )


def _codex_runner_enabled() -> bool:
    # Explicit second gate for real Codex (personal manual smoke only). Tolerate misspelling.
    return _env_flag(
        "MCHARNESS_CODEX_RUNNER_ENABLED",
        "MCHARNESSS_CODEX_RUNNER_ENABLED",
        default="false",
    )


def _safe_cmd(cmd: list[str], timeout: float = 2.5, cwd: str | None = None) -> subprocess.CompletedProcess | None:
    """Run a command with timeout; never raise, always return structured result or None."""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except Exception:
        return None


def _detect_executable(name: str) -> dict[str, Any]:
    """Safe, non-interactive detection using command -v + optional --version. No auth files, no login, no secrets."""
    exe: Optional[str] = None
    version: Optional[str] = None
    # Per spec: use command -v
    res = _safe_cmd(["bash", "-c", f"command -v {name} || true"], timeout=2.0)
    if res is not None and res.returncode == 0 and res.stdout.strip():
        exe = res.stdout.strip().splitlines()[0].strip() or None
    if exe:
        # Try --version (or -v for some); tolerate non-zero (some CLIs print version to stderr)
        for args in ([exe, "--version"], [exe, "-v"], [exe, "--help"]):
            vres = _safe_cmd(args, timeout=3.0)
            if vres is not None and (vres.stdout or vres.stderr):
                version = (vres.stdout or vres.stderr).strip().splitlines()[0][:140]
                break
    return {
        "installed": bool(exe),
        "executable_path": exe,
        "version": version,
    }


def _get_git_status(path: Path) -> dict[str, Any]:
    """Safe git status for allowlisted repo only. Timeouts, no arbitrary paths."""
    if not path.exists() or not (path / ".git").exists():
        return {
            "current_branch": None,
            "dirty": False,
            "changed_files_count": 0,
            "last_commit_short": None,
            "status_summary": "unavailable (no .git)",
            "safety_notes": ["git metadata unavailable"],
        }
    info: dict[str, Any] = {}
    for cmd, key in (
        (["git", "rev-parse", "--abbrev-ref", "HEAD"], "current_branch"),
        (["git", "rev-parse", "--short", "HEAD"], "last_commit_short"),
    ):
        r = _safe_cmd(cmd, timeout=2.0, cwd=str(path))
        info[key] = r.stdout.strip() if (r is not None and r.returncode == 0) else None
    r = _safe_cmd(["git", "status", "--porcelain"], timeout=3.0, cwd=str(path))
    if r is not None and r.returncode == 0:
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        info["changed_files_count"] = len(lines)
        info["dirty"] = len(lines) > 0
    else:
        info["changed_files_count"] = 0
        info["dirty"] = False
    branch = info.get("current_branch") or ""
    summary = f"{'dirty' if info.get('dirty') else 'clean'} ({info.get('changed_files_count', 0)} changed)"
    if branch:
        summary += f" on {branch}"
    info["status_summary"] = summary
    info["safety_notes"] = []
    return info


def _require_public_write_access(request: Request) -> None:
    if _public_write_enabled():
        return
    expected_token = os.getenv("MCHARNESS_ADMIN_TOKEN", "").strip()
    presented_token = request.headers.get("X-MCHarness-Admin-Token", "").strip()
    if expected_token and presented_token == expected_token:
        return
    raise HTTPException(
        status_code=403,
        detail="Public write access is disabled for this deployment.",
    )

class TaskCreateRequest(BaseModel):
    task_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    title: str
    description: str
    command: str
    args: List[str] = Field(default_factory=list)

class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "edit_state"]
    actor: str
    reviewer_note: Optional[str] = None
    state_patch: Dict[str, Any] = Field(default_factory=dict)


class McHarnessSessionCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    plan_instruction: str = Field(min_length=1)
    repo_path: str = Field(min_length=1)
    agent_lane: str = Field(min_length=1)


class McHarnessQueueRequest(BaseModel):
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    target_role: Literal["ui_inspector", "safety_auditor", "test_runner", "implementer", "docs_writer", "reviewer"] = "reviewer"
    file_scope: list[str] = Field(default_factory=list)
    forbidden_file_scope: list[str] = Field(default_factory=list)
    evidence_required: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)


class McHarnessPromptExportRequest(BaseModel):
    queue_item_id: str = Field(min_length=1)
    mark_sent: bool = False


class McHarnessManualResultRequest(BaseModel):
    assignment_id: Optional[str] = None
    summary: str = Field(min_length=1)
    transcript: Optional[str] = None
    source_ref: Optional[str] = None
    verdict: Literal["passed", "unknown", "blocked", "failed"] = "passed"
    complete_assignment: bool = False
    git_status: Optional[str] = None
    git_diff_summary: Optional[str] = None
    test_output: Optional[str] = None


class McHarnessGateDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "edit_requested"]
    note: Optional[str] = None
    continue_after: bool = False


class McHarnessRunnerIntentRequest(BaseModel):
    lane_id: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    queue_item_id: Optional[str] = None
    prompt_artifact_id: Optional[str] = None
    mode: str = "dry_run"


class McHarnessRunnerStartRequest(BaseModel):
    lane_id: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    queue_item_id: Optional[str] = None
    prompt_artifact_id: Optional[str] = None
    title: Optional[str] = None
    prompt: Optional[str] = None
    branch: Optional[str] = None
    plan_id: Optional[str] = None
    agent_id: Optional[str] = None
    created_by: Optional[str] = "operator"


class WardenMemoryRecallRequest(BaseModel):
    query: str = Field(default="")
    project_id: str = Field(min_length=1, max_length=160)
    limit: int = Field(default=20, ge=1, le=100)


class WardenMemoryContextPackRequest(BaseModel):
    project_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$",
    )
    repo_path: Optional[str] = Field(default=None, max_length=500)
    agent: Optional[str] = Field(default=None, max_length=80)
    prompt: str = Field(default="", max_length=20_000)
    branch: Optional[str] = Field(default=None, max_length=200)
    task_id: Optional[str] = Field(default=None, max_length=160)
    max_memories: int = Field(default=8, ge=1, le=50)
    max_chars: int = Field(default=6000, ge=256, le=20_000)


class McHarnessRunEvidenceCreateRequest(BaseModel):
    type: str = Field(default="transcript", min_length=1)
    title: str = Field(min_length=1)
    summary: Optional[str] = None
    content_excerpt: Optional[str] = None
    content: Optional[str] = None
    agent_id: Optional[str] = None
    source: str = Field(default="operator", min_length=1)


class McHarnessProofGateCreateRequest(BaseModel):
    gate_type: str = Field(default="manual_review", min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(default="")
    plan_id: Optional[str] = None
    step_id: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)


class McHarnessProofGateDecisionRequest(BaseModel):
    decision: Literal["approve", "block", "request_more_evidence"]
    decided_by: str = Field(default="operator", min_length=1)
    decision_reason: Optional[str] = None


class McHarnessCaptainPlanRequest(BaseModel):
    goal: str = Field(min_length=1)
    repo_id: str = Field(min_length=1)
    lane_id: str = Field(min_length=1)


class McHarnessCaptainKeyRequest(BaseModel):
    api_key: str = Field(min_length=1)
    model: str = Field(default="openrouter/auto", min_length=1)


class McHarnessCaptainPlanStep(BaseModel):
    id: str
    title: str
    agent: str
    prompt: str
    status: Literal["queued"] = "queued"


class McHarnessCaptainPlanResponse(BaseModel):
    ok: bool = True
    plan_id: str
    title: str
    summary: str
    steps: list[McHarnessCaptainPlanStep]
    notes: list[str] = Field(default_factory=list)
    goal: Optional[str] = None
    repo_id: Optional[str] = None
    status: Optional[str] = None
    current_step_id: Optional[str] = None
    decision_log: list[dict[str, Any]] = Field(default_factory=list)
    source: Optional[str] = None


class McHarnessCaptainPlanPersistRequest(BaseModel):
    goal: str = Field(min_length=1)
    repo_id: Optional[str] = None
    plan_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    steps: list[dict[str, Any]] = Field(default_factory=list)


class McHarnessCaptainStepCompleteRequest(BaseModel):
    evidence_ids: list[str] = Field(default_factory=list)


class McHarnessCaptainStepReviseRequest(BaseModel):
    title: Optional[str] = None
    prompt: Optional[str] = None
    note: Optional[str] = None


class McHarnessCaptainPlanStopRequest(BaseModel):
    note: Optional[str] = None


class McHarnessMissionPauseRequest(BaseModel):
    note: Optional[str] = None


class McHarnessMissionAdjustPlanRequest(BaseModel):
    note: Optional[str] = None
    adjustments: dict[str, Any] = Field(default_factory=dict)


class McHarnessRunnerSessionCleanupRequest(BaseModel):
    confirm: bool = False
    stale_after_seconds: int = Field(default=7200, ge=60, le=604800)


class McHarnessCaptainStatusResponse(BaseModel):
    ok: bool = True
    configured: bool
    provider: Literal["openrouter"] = "openrouter"
    model: str
    planning_enabled: bool
    key_source: Literal["env", "saved", "missing"]
    private_key_setup_enabled: bool
    notes: list[str] = Field(default_factory=list)


class McHarnessCaptainKeyResponse(BaseModel):
    ok: bool = True
    configured: bool
    provider: Literal["openrouter"] = "openrouter"
    model: str
    key_source: Literal["env", "saved", "missing"]
    private_key_setup_enabled: bool
    notes: list[str] = Field(default_factory=list)


def safe_path_exists(path: Path) -> dict[str, Any]:
    try:
        exists = path.exists()
        return {"exists": exists, "accessible": True, "error": None}
    except (PermissionError, OSError) as e:
        return {"exists": False, "accessible": False, "error": str(e)}

def _repo_entries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in SAFE_REPO_PATHS:
        safe_stat = safe_path_exists(path)
        base = {
            "repo_id": path.name,
            "label": path.name,
            "path": str(path),
            "exists": safe_stat["exists"],
            "accessible": safe_stat["accessible"],
            "error": safe_stat["error"],
        }
        
        git_dir_exists = False
        if safe_stat["exists"]:
            git_stat = safe_path_exists(path / ".git")
            git_dir_exists = git_stat["exists"]
            
        base["git_dir_present"] = git_dir_exists

        if safe_stat["exists"] and git_dir_exists:
            try:
                git_info = _get_git_status(path)
            except Exception as e:
                git_info = {
                    "current_branch": None,
                    "dirty": False,
                    "changed_files_count": 0,
                    "last_commit_short": None,
                    "status_summary": "unavailable",
                    "safety_notes": [f"git status failed: {e}"],
                }
        else:
            notes = []
            if not safe_stat["accessible"]:
                notes.append(f"inaccessible: {safe_stat['error']}")
            elif not safe_stat["exists"]:
                notes.append("path does not exist")
            elif not git_dir_exists:
                notes.append("not a git repo")
                
            git_info = {
                "current_branch": None,
                "dirty": False,
                "changed_files_count": 0,
                "last_commit_short": None,
                "status_summary": "unavailable",
                "safety_notes": notes,
            }
        base.update(git_info)
        rows.append(base)
    return rows


def _captain_env_api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip()


def _captain_model_name() -> str:
    value = os.getenv("MCHARNESS_CAPTAIN_MODEL", "openrouter/auto").strip()
    return value or "openrouter/auto"


def _captain_secret_path() -> Path:
    return MCTABLE_ROOT / "secrets" / "captain_openrouter.json"


def _captain_saved_config() -> dict[str, Any] | None:
    path = _captain_secret_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    api_key = str(data.get("api_key") or "").strip()
    if not api_key:
        return None
    return {
        "provider": "openrouter",
        "api_key": api_key,
        "model": str(data.get("model") or "").strip() or _captain_model_name(),
        "updated_at": str(data.get("updated_at") or "").strip(),
    }


def _captain_key_source() -> str:
    if _captain_env_api_key():
        return "env"
    if _captain_saved_config():
        return "saved"
    return "missing"


def _captain_api_key() -> str:
    env_key = _captain_env_api_key()
    if env_key:
        return env_key
    saved = _captain_saved_config()
    return str(saved["api_key"]).strip() if saved else ""


def _captain_effective_model_name() -> str:
    if _captain_env_api_key():
        return _captain_model_name()
    saved = _captain_saved_config()
    if saved and str(saved.get("model") or "").strip():
        return str(saved["model"]).strip()
    return _captain_model_name()


def _captain_private_key_setup_enabled() -> bool:
    return _public_write_enabled() and _tmux_runner_enabled() and _codex_runner_enabled()


def _codex_runner_ready() -> bool:
    return _tmux_runner_enabled() and _codex_runner_enabled()


def _service_mode_label() -> str:
    return "private" if _codex_runner_ready() else "public"


def _run_history_write_enabled() -> bool:
    return _codex_runner_ready()


def _run_history_read_enabled() -> bool:
    return _codex_runner_ready()


def _require_private_memory_access() -> None:
    if not _codex_runner_ready():
        raise HTTPException(
            status_code=403,
            detail="Warden Memory is available only on the private runner service.",
        )


def _require_run_history_write(request: Request) -> None:
    if _run_history_write_enabled():
        return
    raise HTTPException(
        status_code=403,
        detail="Run history writes require the private runner service.",
    )


def _agent_registry_write_enabled() -> bool:
    return _captain_private_key_setup_enabled()


def _agent_registry_private_only() -> bool:
    return not _codex_runner_ready() or _agent_registry_write_enabled()


def _codex_probe_payload() -> dict[str, Any]:
    det = _detect_executable("codex")
    return {
        "installed": bool(det.get("installed")),
        "executable_path": det.get("executable_path"),
        "version": det.get("version"),
    }


def _resolve_captain_plan_agent(agent_id: str) -> dict[str, Any]:
    agent = get_agent_by_id(
        MCTABLE_ROOT,
        agent_id,
        codex_runner_ready=_codex_runner_ready(),
        private_only=_agent_registry_private_only(),
    )
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unknown agent lane: {agent_id}")
    if agent.get("adapter") != "codex_cli":
        raise HTTPException(status_code=400, detail="Captain Deck currently deploys to the Codex CLI lane only.")
    return agent


def _captain_status_payload() -> dict[str, Any]:
    key_source = _captain_key_source()
    configured = key_source in {"env", "saved"}
    notes = []
    if not configured:
        notes.append("Captain is not configured. Set OPENROUTER_API_KEY on the private service.")
    elif key_source == "env":
        notes.append("Captain is configured via environment.")
    else:
        notes.append("Captain is configured via saved private key.")
    return {
        "ok": True,
        "configured": configured,
        "provider": "openrouter",
        "model": _captain_effective_model_name(),
        "planning_enabled": configured,
        "key_source": key_source,
        "private_key_setup_enabled": _captain_private_key_setup_enabled(),
        "notes": notes,
    }


def _validate_captain_api_key_value(api_key: str) -> None:
    key = (api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="OpenRouter API key is required.")
    if not re.match(r"^sk-or-[A-Za-z0-9._-]{8,}$", key):
        raise HTTPException(status_code=400, detail="OpenRouter API key does not look valid.")


def _write_captain_saved_config(api_key: str, model: str) -> None:
    path = _captain_secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except Exception:
        pass
    payload = {
        "provider": "openrouter",
        "api_key": api_key.strip(),
        "model": (model or _captain_model_name()).strip() or "openrouter/auto",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _delete_captain_saved_config() -> bool:
    path = _captain_secret_path()
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to remove saved Captain key.")


def _resolve_allowlisted_repo(repo_id: str) -> tuple[Path, dict[str, Any]]:
    repo = next((item for item in _repo_entries() if item["repo_id"] == repo_id or item["path"] == repo_id), None)
    if repo is None:
        raise HTTPException(status_code=400, detail=f"Unknown repo_id: {repo_id}")
    path = Path(repo["path"])
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Allowlisted repo path does not exist: {repo_id}")
    return path, repo


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate_text = (text or "").strip()
    if not candidate_text:
        raise ValueError("OpenRouter returned an empty response.")

    candidates = [candidate_text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate_text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    first = candidate_text.find("{")
    last = candidate_text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(candidate_text[first:last + 1].strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("OpenRouter response was not valid JSON.")


def _captain_prompt_wrapper(*, goal: str, repo: dict[str, Any], lane_id: str, plan_title: str, plan_summary: str, step_index: int, step_total: int, step_title: str, step_prompt: str) -> str:
    return "\n".join([
        f"Captain Deck step {step_index}/{step_total}: {step_title}",
        f"Exact goal: {goal}",
        f"Plan title: {plan_title}",
        f"Plan summary: {plan_summary}",
        f"Repo: {repo['repo_id']} ({repo['path']})",
        f"Agent lane: {lane_id}",
        "",
        f"Step focus from Captain: {step_prompt}",
        "Inspect before edit.",
        "Known files/areas to inspect: start with the repo surface, then narrow only to the files needed for this step.",
        "Allowed files/areas: only the selected repo and the files needed for this step.",
        "Forbidden actions: no push, merge, reset, rebase, no secrets, no public runner changes, no arbitrary shell input, no deploy commands unless the user explicitly asks later.",
        "Acceptance checks: finish with a concise proof of files inspected, edits made, and verification performed.",
        "Final proof format: branch, commit hash if any, files changed, tests run/output, and remaining unproven items.",
    ])


def _openrouter_chat_completion(*, messages: list[dict[str, str]], model: str, timeout: float = 30.0) -> dict[str, Any]:
    api_key = _captain_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Captain is not configured. Set OPENROUTER_API_KEY on the private service.",
        )
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    request = URLRequest(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Title": "McHarness Captain Deck",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        detail = body.strip() or f"OpenRouter request failed with HTTP {exc.code}."
        raise HTTPException(status_code=502, detail=detail) from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"OpenRouter request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="OpenRouter request timed out.") from exc

    try:
        return json.loads(raw_body)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="OpenRouter returned invalid JSON.") from exc


def _build_captain_plan(*, goal: str, repo: dict[str, Any], lane_id: str) -> tuple[dict[str, Any], list[str]]:
    model = _captain_effective_model_name()
    system_prompt = "\n".join([
        "You are Captain Deck for McHarness.",
        "Output strict JSON only.",
        "Create a bounded plan with 3 to 7 ordered steps.",
        "Each step must be suitable as a Codex dispatch prompt.",
        "The JSON object must contain: title, summary, steps.",
        "Each step object must contain: title and prompt.",
        "Keep each step short, specific, and safe.",
        "Each step prompt must mention the exact goal, files or areas to inspect if known, allowed files or areas if known, forbidden actions, acceptance checks, and a final proof format.",
        "Do not include markdown fences, commentary, or extra keys unless needed for notes.",
        "Do not propose deploy commands unless explicitly requested later.",
        "Default to inspect before edit.",
        "Default to no push, merge, reset, or rebase.",
        "Default to no secrets and no public runner changes.",
    ])
    user_prompt = "\n".join([
        f"Goal: {goal}",
        f"Repo: {repo['repo_id']} ({repo['path']})",
        f"Lane: {lane_id}",
        "Return only JSON with title, summary, and 3-7 ordered steps.",
    ])
    payload = _openrouter_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=model,
        timeout=30.0,
    )
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise HTTPException(status_code=502, detail="OpenRouter response did not include any choices.")
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    message = first_choice.get("message") if isinstance(first_choice, dict) else {}
    content = ""
    if isinstance(message, dict):
        content = str(message.get("content") or "").strip()

    try:
        parsed = _extract_json_object(content)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    title = str(parsed.get("title") or f"Captain plan for {goal[:60]}").strip()
    summary = str(parsed.get("summary") or goal).strip()
    raw_steps = parsed.get("steps")
    if not isinstance(raw_steps, list) or not (3 <= len(raw_steps) <= 7):
        raise HTTPException(status_code=502, detail="Captain plan must contain 3 to 7 ordered steps.")

    steps: list[dict[str, Any]] = []
    notes: list[str] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise HTTPException(status_code=502, detail="Captain plan steps must be JSON objects.")
        step_title = str(raw_step.get("title") or f"Step {index}").strip()
        step_prompt = str(raw_step.get("prompt") or "").strip()
        if not step_prompt:
            raise HTTPException(status_code=502, detail=f"Captain plan step {index} is missing a prompt.")
        steps.append(
            {
                "id": f"step_{index}",
                "title": step_title,
                "agent": lane_id,
                "prompt": _captain_prompt_wrapper(
                    goal=goal,
                    repo=repo,
                    lane_id=lane_id,
                    plan_title=title,
                    plan_summary=summary,
                    step_index=index,
                    step_total=len(raw_steps),
                    step_title=step_title,
                    step_prompt=step_prompt,
                ),
                "status": "queued",
            }
        )

    notes.append(f"OpenRouter model: {model}")
    return {
        "ok": True,
        "plan_id": f"plan_{uuid.uuid4().hex[:8]}",
        "title": title,
        "summary": summary,
        "steps": steps,
        "notes": notes,
    }, notes


def _save_captain_plan_artifact(plan: dict[str, Any], *, goal: str, repo: dict[str, Any], lane_id: str) -> Optional[Path]:
    try:
        CAPTAIN_PLAN_ROOT.mkdir(parents=True, exist_ok=True)
        plan_path = CAPTAIN_PLAN_ROOT / f"{plan['plan_id']}.json"
        artifact = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "goal": goal,
            "repo_id": repo["repo_id"],
            "repo_path": repo["path"],
            "lane_id": lane_id,
            "plan": plan,
        }
        plan_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        return plan_path
    except Exception:
        return None


def _captain_plan_response(plan: dict[str, Any], *, notes: list[str] | None = None) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    current_step_id = plan.get("current_step_id")
    current_gate_status: str | None = None
    for step in plan.get("steps") or []:
        step_id = step.get("step_id") or step.get("id")
        run_id = step.get("run_id")
        gate_status = gate_status_summary_for_run(MCTABLE_ROOT, str(run_id)) if run_id else None
        if step_id == current_step_id:
            current_gate_status = gate_status
        steps.append(
            {
                "id": step_id,
                "title": step.get("title"),
                "agent": step.get("agent_id") or step.get("agent") or "codex_cli",
                "prompt": step.get("prompt") or step.get("prompt_preview") or "",
                "status": step.get("status"),
                "run_id": run_id,
                "evidence_ids": list(step.get("evidence_ids") or []),
                "gate_status": gate_status,
                "gate_label": gate_ui_label(gate_status),
            }
        )
    return {
        "ok": True,
        "plan_id": plan.get("plan_id"),
        "title": plan.get("title"),
        "summary": plan.get("summary"),
        "goal": plan.get("goal"),
        "repo_id": plan.get("repo_id"),
        "status": plan.get("status"),
        "current_step_id": current_step_id,
        "current_gate_status": current_gate_status,
        "current_gate_label": gate_ui_label(current_gate_status),
        "steps": steps,
        "decision_log": list(plan.get("decision_log") or []),
        "notes": list(notes or []),
    }


def _execute_codex_dispatch_for_step(
    *,
    title: str,
    prompt: str,
    repo_id: str,
    plan_id: str | None = None,
    step_id: str | None = None,
) -> dict[str, Any]:
    if not _codex_runner_ready():
        raise HTTPException(status_code=403, detail="Codex dispatch requires the private runner service.")
    repo_path, _repo = _resolve_allowlisted_repo(repo_id)
    session = create_mcharness_session(
        McHarnessSessionCreateRequest(
            title=title,
            objective=title,
            plan_instruction=prompt,
            repo_path=str(repo_path),
            agent_lane="codex_cli",
        )
    )
    session_id = session["session_id"]
    queue_result = queue_mcharness_prompt(
        session_id,
        McHarnessQueueRequest(title=title, prompt=prompt),
    )
    queue_item_id = queue_result.get("queue_item_id")
    runner_state = post_mcharness_runner_start(
        session_id,
        McHarnessRunnerStartRequest(
            lane_id="codex_cli",
            repo_id=repo_id,
            queue_item_id=queue_item_id,
            title=title,
            prompt=prompt,
            plan_id=plan_id,
            agent_id="codex_cli",
            created_by="captain_loop",
        ),
    )
    return {
        "session_id": session_id,
        "runner_id": runner_state.get("runner_id"),
        "queue_item_id": queue_item_id,
        "prompt": runner_state.get("dispatch_prompt") or prompt,
        "runner_state": runner_state,
    }


def _lane_entries() -> list[dict[str, Any]]:
    """Return rich lane objects (new fields) + legacy keys for compat. Safe checks only."""
    now = datetime.now(timezone.utc).isoformat()
    tmux_enabled = _tmux_runner_enabled()
    # base static for order + validation compat
    base_map = {entry["lane_id"]: entry for entry in AGENT_LANES}

    def _rich_for(lid: str, label: str, desc: str, is_manual: bool = False) -> dict[str, Any]:
        if is_manual:
            det = {"installed": True, "executable_path": None, "version": None}
            auth = "not_checked"
            rmode = "manual"
            notes = ["Manual paste-back flow. Operator performs all CLI steps locally. No server-side execution."]
        elif lid == "fake_test_lane":
            det = {"installed": True, "executable_path": None, "version": "internal-fake-1.0"}
            auth = "not_checked"
            rmode = "controlled_run_ready"
            notes = [
                "FAKE TEST LANE: harmless python -c print only. No provider calls, no usage burn, no real CLI.",
                "For automated tests and proof only. Gated behind MCHARNESS_TMUX_RUNNER_ENABLED or test override.",
            ]
        else:
            det = _detect_executable(lid.split("_")[0])  # codex or agy
            auth = "unknown" if det["installed"] else "not_detected"
            rmode = "dry_run_ready" if det["installed"] else "controlled_run_disabled"
            notes = []
            if lid == "codex_cli":
                # Improve auth for codex using safe non-int doctor (no secrets, no login)
                if det["installed"]:
                    exe = det["executable_path"]
                    dres = _safe_cmd([exe, "doctor"], timeout=5.0)
                    dout = ((dres.stdout or "") + (dres.stderr or "")).lower() if dres else ""
                    if dres is not None and (dres.returncode == 0) and any(k in dout for k in ["authenticated", "logged in", "ready", "health"]):
                        auth = "likely_ready"
                    else:
                        auth = "unknown"
                    tmux_f = _tmux_runner_enabled()
                    codex_f = _codex_runner_enabled()
                    rmode = "controlled_run_ready" if (det["installed"] and tmux_f and codex_f) else "controlled_run_disabled"
                    notes.append("Real Codex gated: requires BOTH MCHARNESS_TMUX_RUNNER_ENABLED=true AND MCHARNESS_CODEX_RUNNER_ENABLED=true for controlled start.")
                    notes.append("Uses codex exec (non-int) + --cd + --output-last-message for transcript. Attach mode fallback via tmux if needed.")
                    notes.append("Auth via safe non-interactive 'codex doctor' check only; no token files or login commands ever inspected.")
                else:
                    notes.append("Codex not found via command -v. Install via subscription to enable (preview still works).")
            elif det["installed"]:
                notes.append("Real execution disabled (public_manual + MCHARNESS_TMUX_RUNNER_ENABLED=false).")
                notes.append("Dry-run intent preview supported. No auth files, cookies, or secrets are inspected.")
            else:
                notes.append("Executable not found via command -v. Install via your subscription to enable (preview still works).")
        legacy = base_map.get(lid, {"implemented": False, "manual_only": True})
        return {
            "id": lid,
            "label": label,
            "description": desc,
            "installed": det["installed"],
            "executable_path": det["executable_path"],
            "version": det["version"],
            "auth_status": auth,
            "runner_mode": rmode,
            "safety_notes": notes,
            "last_checked_at": now,
            # legacy for existing UI/tests
            "lane_id": lid,
            "title": label,
            "implemented": legacy.get("implemented", not is_manual),
            "manual_only": True,
        }

    rich = [
        _rich_for("codex_cli", "Codex CLI", "OpenAI Codex CLI for code generation/edits via subscription."),
        _rich_for("agy_cli", "AGY / Antigravity CLI", "AGY/Antigravity CLI coding agent (subscription)."),
        _rich_for("manual_paste", "Manual paste-back", "Copy prompt export and paste transcript/results back manually.", is_manual=True),
        _rich_for("grok_placeholder", "Grok", "Grok CLI (placeholder, not wired for preview)."),
        _rich_for("jules_placeholder", "Jules", "Jules (placeholder, not wired for preview)."),
        _rich_for("opencode_placeholder", "OpenCode", "OpenCode (placeholder, not wired for preview)."),
        _rich_for("fake_test_lane", "Fake Test Lane (internal/harmless for automated proof only)", "Internal fake lane for runner foundation tests/proof. Harmless python -c only."),
    ]
    # also surface tmux availability in notes for cli lanes if useful
    tmux_note = f"tmux available: {bool(_safe_cmd(['bash', '-c', 'command -v tmux || true'], timeout=1.0))}"
    for entry in rich:
        if entry["id"] in ("codex_cli", "agy_cli") and entry["installed"]:
            entry["safety_notes"].append(tmux_note)
    return rich


def _validate_repo_path(repo_path: str) -> Path:
    for entry in SAFE_REPO_PATHS:
        if str(entry) == repo_path or entry.name == repo_path: # Allow matching by repo_id (name)
            safe_stat = safe_path_exists(entry)
            if not safe_stat["accessible"]:
                raise HTTPException(status_code=400, detail=f"Allowlisted repo path inaccessible ({safe_stat['error']}): {repo_path}")
            if not safe_stat["exists"]:
                raise HTTPException(status_code=400, detail=f"Allowlisted repo path does not exist: {repo_path}")
            return entry
    raise HTTPException(status_code=400, detail=f"Repo path is not allowlisted: {repo_path}")


def _validate_agent_lane(agent_lane: str) -> dict[str, Any]:
    lane = next((entry for entry in AGENT_LANES if entry["lane_id"] == agent_lane), None)
    if lane is None:
        raise HTTPException(status_code=400, detail=f"Unknown agent lane: {agent_lane}")
    if not lane["implemented"]:
        raise HTTPException(status_code=400, detail=f"Agent lane is placeholder only: {agent_lane}")
    return lane


def _thread_for_session(session_id: str) -> dict[str, Any]:
    try:
        return WORKBENCH_STORE.get_thread(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}") from exc


def _run_for_session(session_id: str) -> dict[str, Any]:
    runs = WORKBENCH_STORE.list_runs_for_thread(session_id)
    if not runs:
        raise HTTPException(status_code=404, detail=f"No run found for session: {session_id}")
    return runs[0]


def _append_run_event(run_id: str, title: str, detail: str, severity: str = "info", event_type: str = "note") -> None:
    WORKBENCH_STORE.append_run_event(
        run_id,
        WorkbenchRunEventCreateRequest(
            event_type=event_type,
            title=title,
            detail=detail,
            severity=severity,  # type: ignore[arg-type]
        ),
    )


def _artifact_blob_path(thread_id: str, kind: str, extension: str) -> Path:
    suffix = extension.lstrip(".") or "txt"
    target_dir = ARTIFACT_BODY_ROOT / thread_id
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{kind}-{uuid.uuid4().hex[:8]}.{suffix}"


def _create_artifact(thread_id: str, kind: str, title: str, body: str, summary: Optional[str] = None, extension: str = "txt") -> dict[str, Any]:
    path = _artifact_blob_path(thread_id, kind, extension)
    path.write_text(body, encoding="utf-8")
    artifact = WORKBENCH_STORE.create_artifact(
        WorkbenchArtifactCreateRequest(
            artifact_id=f"artifact_{uuid.uuid4().hex[:8]}",
            kind=kind,
            title=title,
            path=str(path),
            thread_id=thread_id,
            summary=summary or title,
            notes=None,
        )
    )
    return artifact.model_dump(mode="json")


def _create_run_summary_artifact(thread: dict[str, Any], run: dict[str, Any], note: str) -> dict[str, Any]:
    metadata = thread.get("metadata") or {}
    body = "\n".join(
        [
            "# McHarness Run Summary",
            f"- Session: {thread.get('title')}",
            f"- Session id: {thread.get('thread_id')}",
            f"- Repo/worktree: {metadata.get('repo_path', '(unknown)')}",
            f"- CLI lane: {metadata.get('agent_lane', '(unknown)')}",
            f"- Thread status: {thread.get('status')}",
            f"- Run id: {run.get('run_id')}",
            f"- Run status: {run.get('status')}",
            f"- Current step: {run.get('current_step')}",
            f"- Note: {note}",
        ]
    )
    return _create_artifact(thread["thread_id"], "run_summary", "Run summary", body, note, "md")


def _capture_git_status_artifacts(thread: dict[str, Any]) -> dict[str, Any]:
    metadata = thread.get("metadata") or {}
    repo_path = _validate_repo_path(metadata.get("repo_path", ""))
    status_proc = subprocess.run(
        ["git", "-C", str(repo_path), "status", "--short"],
        capture_output=True,
        text=True,
        check=False,
    )
    diff_proc = subprocess.run(
        ["git", "-C", str(repo_path), "diff", "--stat"],
        capture_output=True,
        text=True,
        check=False,
    )
    status_text = status_proc.stdout.strip() or "(clean)"
    diff_text = diff_proc.stdout.strip() or "(no diff summary)"
    status_artifact = _create_artifact(
        thread["thread_id"],
        "git_status",
        "Git status",
        status_text + "\n",
        f"git status for {repo_path}",
        "txt",
    )
    diff_artifact = _create_artifact(
        thread["thread_id"],
        "git_diff_summary",
        "Git diff summary",
        diff_text + "\n",
        f"git diff summary for {repo_path}",
        "txt",
    )
    return {
        "repo_path": str(repo_path),
        "git_status": status_text,
        "git_diff_summary": diff_text,
        "artifacts": [status_artifact, diff_artifact],
    }


# --- Gated tmux runner foundation (fake_test_lane + controlled when enabled) ---

RUNNER_STATE_ROOT = MCTABLE_ROOT / "mcharness" / "runners"


def _runner_state_path(session_id: str) -> Path:
    RUNNER_STATE_ROOT.mkdir(parents=True, exist_ok=True)
    return RUNNER_STATE_ROOT / f"{session_id}.json"


def _load_runner_state(session_id: str) -> Optional[dict[str, Any]]:
    p = _runner_state_path(session_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_runner_state(state: dict[str, Any]) -> None:
    p = _runner_state_path(state["session_id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(p)


def _tmux_session_name(session_id: str, runner_id: str) -> str:
    safe_runner = "".join(c if c.isalnum() or c == "_" else "_" for c in str(runner_id or ""))
    if not safe_runner:
        base = (session_id.replace("-", "") + runner_id.replace("-", ""))[-12:]
        safe_runner = "".join(c if c.isalnum() or c == "_" else "_" for c in base)
    return f"mch_run_{safe_runner}"


def _get_tmux_transcript(name: str) -> str:
    """Prefer live pane capture for running sessions (so monitor shows actual Codex output).
    Fall back to previous file contents on exit.
    """
    if not name:
        return ""
    # Always try capture first if the session exists (live view)
    has = _safe_cmd(["tmux", "has-session", "-t", name], timeout=1.0)
    if has is not None and has.returncode == 0:
        res = _safe_cmd(["tmux", "capture-pane", "-p", "-t", name], timeout=3.0)
        if res is not None and res.returncode == 0:
            return res.stdout or ""
    # session gone or capture failed: use whatever is in the transcript file (final or previous captures)
    # (the file may have been appended to by send or prior captures)
    return ""


def _stop_tmux(name: str) -> None:
    _safe_cmd(["tmux", "kill-session", "-t", name], timeout=2.0)


def _start_fake_runner(state: dict[str, Any]) -> dict[str, Any]:
    """Harmless fake only. Uses pure long-running process in tmux so monitor can capture live + injected prompt text.
    No providers, no usage burn. For automated proof of interactive send/capture/stop.
    """
    name = state["tmux_session_name"]
    # Long-running harmless process (stays alive for send-keys and capture).
    # The typed prompt from send will appear in the tmux pane buffer (visible in capture).
    inner = "python -c \"import time,sys; print('FAKE_STARTED'); sys.stdout.flush(); time.sleep(300)\" "
    tmux_cmd = ["tmux", "new-session", "-d", "-s", name, "--", "bash", "-c", inner]
    res = _safe_cmd(tmux_cmd, timeout=5.0)
    if res is not None and res.returncode == 0:
        state["status"] = "running"
        state["notes"].append("tmux session started for fake_test_lane (long-running for live capture)")
    else:
        state["status"] = "failed"
        state["notes"].append(f"tmux start failed: {getattr(res, 'stderr', 'err') if res else 'subprocess err'}")
    return state


def _skip_codex_update_prompt(name: str) -> bool:
    """Auto-dismiss Codex's update screen if it appears on startup.
    This keeps the private runner on the actual input screen where prompt submission works.
    """
    if not name:
        return False
    pane = _get_tmux_transcript(name)
    if "Update available" not in pane and "Skip until next version" not in pane and "Update now" not in pane:
        return False
    _safe_cmd(["tmux", "send-keys", "-t", name, "2"], timeout=1.0)
    _safe_cmd(["tmux", "send-keys", "-t", name, "Enter"], timeout=1.0)
    time.sleep(1.0)
    return True


def _start_codex_runner(state: dict[str, Any], cwd: str) -> dict[str, Any]:
    """Launch Codex interactively in tmux (pure, no wrapper that forces exit).
    Keeps the tmux session + Codex TUI alive for live monitoring and later prompt injection.
    """
    name = state["tmux_session_name"]
    # Pure interactive launch in the allowlisted cwd. Codex will run its TUI and wait.
    # Use the binary name (resolvable in PATH for the service user).
    tmux_cmd = ["tmux", "new-session", "-d", "-s", name, "-c", cwd, "codex"]
    res = _safe_cmd(tmux_cmd, timeout=5.0)
    if res is not None and res.returncode == 0:
        state["status"] = "waiting_for_codex"
        state["notes"].append("codex interactive tmux session started; will inject prompt after ~10s delay")
        state["attach_command"] = f"tmux attach -t {name}"
        if _skip_codex_update_prompt(name):
            state["notes"].append("codex update prompt auto-skipped on startup")
    else:
        state["status"] = "failed"
        state["notes"].append(f"codex tmux start failed: {getattr(res, 'stderr', 'err') if res else 'subprocess err'}")
        state["attach_command"] = f"tmux attach -t {name}  # (may have failed to start)"
    return state


class McHarnessRunnerSendPrompt(BaseModel):
    prompt: str = Field(min_length=1)


class McHarnessRunnerSendKey(BaseModel):
    key: Literal["1", "2", "3", "Enter", "Esc", "Ctrl+C", "Submit / Continue"]


ALLOWED_QUICK_REPLY_KEYS: dict[str, str] = {
    "1": "1",
    "2": "2",
    "3": "3",
    "Enter": "Enter",
    "Esc": "Escape",
    "Ctrl+C": "C-c",
}

ACTIVE_RUNNER_STATUSES = {"running", "waiting_for_codex", "prompt_sent", "awaiting_response"}


def _runner_transcript_excerpt(state: dict[str, Any], limit: int = 1200) -> str:
    text = _runner_transcript_text(state)
    text = text or ""
    if len(text) > limit:
        return text[-limit:]
    return text


def _resolve_dispatch_prompt(session_id: str, payload: McHarnessRunnerStartRequest) -> tuple[str, str]:
    thread = _thread_for_session(session_id)
    title = (payload.title or thread.get("title") or "Codex run").strip()
    prompt = (payload.prompt or "").strip()
    if not prompt and payload.queue_item_id:
        try:
            prompt = export_captain_queue_item(payload.queue_item_id).strip()
        except Exception:
            prompt = ""
    if not prompt:
        prompt = title
    return title, prompt


def build_agent_prompt_with_memory(
    original_prompt: str,
    *,
    project_id: str,
    repo_path: Optional[str] = None,
    agent: Optional[str] = None,
    branch: Optional[str] = None,
    task_id: Optional[str] = None,
) -> tuple[str, dict[str, Any]]:
    if original_prompt.startswith("# Warden Memory Context"):
        return original_prompt, {
            "memory_count": 0,
            "memory_ids": [],
            "truncated": False,
            "scope": project_id,
            "injected": False,
            "already_injected": True,
        }
    try:
        pack = WORKBENCH_STORE.build_memory_context_pack(
            project_id=project_id,
            repo_path=repo_path,
            agent=agent,
            user_prompt=original_prompt,
            branch=branch,
            task_id=task_id,
        )
    except Exception:
        return original_prompt, {
            "memory_count": 0,
            "memory_ids": [],
            "truncated": False,
            "scope": project_id,
            "injected": False,
            "error": "memory_context_unavailable",
        }
    context = str(pack.get("context") or "").strip()
    if not context:
        return original_prompt, {**pack, "injected": False}
    prompt = f"{context}\n\n---\n\n# User Task\n\n{original_prompt}"
    return prompt, {**pack, "injected": True}


def _remember_run_memory(
    *,
    scope: str,
    content: str,
    kind: str,
    title: str,
    source_ref: Optional[str] = None,
    repo_path: Optional[str] = None,
    branch: Optional[str] = None,
    task_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Optional[str]:
    try:
        memory = WORKBENCH_STORE.remember_memory(
            WorkbenchMemoryRememberRequest(
                scope=scope,
                content=content[:4000],
                source="warden",
                title=title[:160],
                source_ref=source_ref,
                tags=list(tags or []),
                kind=kind,
                project_id=scope,
                repo_path=repo_path,
                branch=branch,
                task_id=task_id,
                agent_id=agent_id,
                compacted=True,
            )
        )
        return memory.memory_id
    except Exception:
        return None


def _create_warden_run_on_dispatch(
    session_id: str,
    payload: McHarnessRunnerStartRequest,
    *,
    runner_id: str,
    transcript_path: str,
    status: str = "dispatched",
    original_prompt: Optional[str] = None,
) -> dict[str, Any] | None:
    if payload.lane_id != "codex_cli" or not _run_history_write_enabled():
        return None
    title, prompt = _resolve_dispatch_prompt(session_id, payload)
    return create_run_record(
        MCTABLE_ROOT,
        run_id=runner_id,
        title=title,
        agent_id=payload.agent_id or "codex_cli",
        agent_adapter="codex_cli",
        repo_id=payload.repo_id,
        branch=payload.branch,
        prompt=prompt,
        status=status,
        session_id=session_id,
        plan_id=payload.plan_id,
        transcript_path=transcript_path,
        created_by=payload.created_by or "operator",
        service_mode=_service_mode_label(),
        original_prompt=original_prompt,
    )


def _sync_warden_run_from_runner_state(state: dict[str, Any], *, status: str | None = None, completed: bool = False) -> None:
    if not _run_history_write_enabled():
        return
    runner_id = state.get("runner_id")
    if not runner_id:
        return
    patch: dict[str, Any] = {
        "transcript_excerpt": _runner_transcript_excerpt(state),
        "transcript_path": state.get("transcript_file_path"),
    }
    if status:
        patch["status"] = status
    if completed:
        patch["completed_at"] = datetime.now(timezone.utc).isoformat()
    update_run_record(MCTABLE_ROOT, str(runner_id), **patch)


def _runner_transcript_text(state: dict[str, Any]) -> str:
    name = state.get("tmux_session_name", "")
    if name:
        live = _get_tmux_transcript(name)
        if live:
            return live
    transcript_path = state.get("transcript_file_path")
    if transcript_path:
        p = Path(transcript_path)
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                return ""
    return ""


def _send_key_to_codex_runner(session_id: str, key: str) -> dict[str, Any]:
    state = _load_runner_state(session_id)
    if not state or state.get("lane_id") != "codex_cli":
        raise HTTPException(status_code=400, detail="Quick reply only supported for active codex_cli runner")
    if state.get("session_id") != session_id:
        raise HTTPException(status_code=400, detail="Runner state/session mismatch")

    status = state.get("status")
    if status not in ACTIVE_RUNNER_STATUSES:
        raise HTTPException(status_code=409, detail=f"Runner not active (status={status or 'unknown'})")

    name = state.get("tmux_session_name")
    if not name:
        raise HTTPException(status_code=400, detail="No tmux session for runner")
    expected_name = _tmux_session_name(session_id, str(state.get("runner_id", "")))
    if name != expected_name:
        raise HTTPException(status_code=400, detail="Runner tmux session mismatch")

    has = _safe_cmd(["tmux", "has-session", "-t", name], timeout=1.0)
    if has is None or has.returncode != 0:
        raise HTTPException(status_code=409, detail="No active tmux session for runner")

    status_note = None
    if key == "Submit / Continue":
        res_tab = _safe_cmd(["tmux", "send-keys", "-t", name, "Tab"], timeout=2.5)
        res_enter = _safe_cmd(["tmux", "send-keys", "-t", name, "Enter"], timeout=2.5)
        if res_tab is None or res_tab.returncode != 0 or res_enter is None or res_enter.returncode != 0:
            raise HTTPException(status_code=502, detail="Failed to submit prompt to tmux runner")
        status_note = "Prompt sent to Codex."
    else:
        tmux_key = ALLOWED_QUICK_REPLY_KEYS.get(key)
        if tmux_key is None:
            raise HTTPException(status_code=400, detail="Unsupported quick reply key")

        res = _safe_cmd(["tmux", "send-keys", "-t", name, tmux_key], timeout=2.5)
        if res is None or res.returncode != 0:
            raise HTTPException(status_code=502, detail="Failed to send quick reply to tmux runner")

    try:
        run = _run_for_session(session_id)
        if key == "Submit / Continue":
            _append_run_event(run.get("run_id", ""), "Prompt sent to Codex", "Prompt sent to Codex via tmux Tab + Enter", "info", "runner")
        else:
            _append_run_event(run.get("run_id", ""), "Quick reply sent", f"Sent quick reply key {key!r} to Codex via tmux", "info", "runner")
    except Exception:
        pass

    return {
        "ok": True,
        "session_id": session_id,
        "runner_id": state.get("runner_id"),
        "lane_id": state.get("lane_id"),
        "tmux_session_name": name,
        "sent_key": key,
        "status": state.get("status"),
        "status_note": status_note,
        "transcript_excerpt": _runner_transcript_excerpt(state),
    }


def _send_prompt_to_codex_runner(session_id: str, prompt_text: str):
    """Safe, allowlisted only: send the (controlled) prompt text to the codex tmux runner via send-keys -l (literal).
    No arbitrary shell. Only called for codex lane after start + delay.
    """
    state = _load_runner_state(session_id)
    if not state or state.get("lane_id") != "codex_cli":
        raise HTTPException(status_code=400, detail="Send prompt only supported for active codex_cli runner")
    name = state.get("tmux_session_name")
    if not name:
        raise HTTPException(status_code=400, detail="No tmux session for runner")
    dispatch_prompt = str(state.get("dispatch_prompt") or "")
    if dispatch_prompt and not prompt_text:
        prompt_text = dispatch_prompt
    # Use -l for literal text (safe, no shell interp of user prompt).
    # Codex CLI queues the message, then Tab + Enter submits it.
    _safe_cmd(["tmux", "send-keys", "-t", name, "-l", prompt_text], timeout=5.0)
    _safe_cmd(["tmux", "send-keys", "-t", name, "Tab"], timeout=2.0)
    _safe_cmd(["tmux", "send-keys", "-t", name, "Enter"], timeout=2.0)
    # append note to transcript file (for final evidence)
    try:
        p = Path(state["transcript_file_path"])
        with p.open("a", encoding="utf-8") as f:
            f.write(f"\n# [McHarness injected prompt @ {datetime.now(timezone.utc).isoformat()}]\n{prompt_text}\n")
    except Exception:
        pass
    state["status"] = "awaiting_response"
    state["notes"].append("prompt text injected via tmux send-keys -l + Tab + Enter; waiting for Codex response")
    _save_runner_state(state)
    _sync_warden_run_from_runner_state(state, status="running")
    try:
        run = _run_for_session(session_id)
        _append_run_event(run.get("run_id", ""), "Prompt sent to Codex", "User task prompt injected via safe tmux send-keys", "info", "runner")
    except Exception:
        pass
    return {
        "ok": True,
        "session_id": session_id,
        "runner_id": state.get("runner_id"),
        "lane_id": state.get("lane_id"),
        "tmux_session_name": name,
        "status": state.get("status"),
        "transcript_excerpt": _runner_transcript_excerpt(state),
    }


@mcharness_router.post("/sessions/{session_id}/runner/send-prompt")
def post_mcharness_runner_send_prompt(session_id: str, payload: McHarnessRunnerSendPrompt):
    """Smallest safe endpoint to inject the modal prompt into the running codex tmux (after startup delay)."""
    result = _send_prompt_to_codex_runner(session_id, payload.prompt)
    return {**result, "ok": True, "injected": True}


@mcharness_router.post("/sessions/{session_id}/runner/send-key")
def post_mcharness_runner_send_key(session_id: str, payload: McHarnessRunnerSendKey):
    return _send_key_to_codex_runner(session_id, payload.key)


@router.get("/capabilities", response_model=List[CapabilityStatus])
def get_capabilities():
    return get_runtime_capabilities()

@router.get("/status")
def get_status():
    return {
        "service": "marius-desktop-api",
        "status": "online",
        "langgraph_available": LANGGRAPH_AVAILABLE,
        "sqlite_checkpointing_available": LANGGRAPH_AVAILABLE,
        "checkpoint_db_path": str(CHECKPOINT_DB_PATH.resolve()),
        "checkpoint_exists": checkpoint_file_exists(),
        "mctable_root": str(MCTABLE_ROOT.resolve())
    }


def _git_branch() -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    branch = proc.stdout.strip()
    return branch or None


def _file_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


@mcharness_router.get("/warden/build-info")
def get_warden_build_info():
    """Proof of what's actually on disk right now — commit, branch, and
    sha256 of the served UI files. Compare against `sha256sum web/warden/*`
    to prove the running service matches the working tree."""
    web_dir = REPO_ROOT / "web" / "warden"
    return {
        "ok": True,
        "commit": _git_commit(),
        "branch": _git_branch(),
        "app_html_hash": _file_sha256(web_dir / "app.html"),
        "app_css_hash": _file_sha256(web_dir / "app.css"),
        "app_js_hash": _file_sha256(web_dir / "app.js"),
    }


@mcharness_router.get("/health")
def get_mcharness_health():
    repos = _repo_entries()
    lanes = _lane_entries()
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "commit": _git_commit(),
        "mode": "public_manual",
        "real_agent_launch_enabled": False,
        "arbitrary_command_execution_enabled": False,
        "public_write_enabled": _public_write_enabled(),
        "tmux_runner_enabled": _tmux_runner_enabled(),
        "codex_runner_enabled": _codex_runner_enabled(),
        "available_lanes_count": len(lanes),
        "repo_count": len(repos),
        "manual_mode": True,
    }


@mcharness_router.get("/captain/status", response_model=McHarnessCaptainStatusResponse)
def get_mcharness_captain_status():
    return _captain_status_payload()


@mcharness_router.post("/captain/key", response_model=McHarnessCaptainKeyResponse, dependencies=[Depends(_require_public_write_access)])
def set_mcharness_captain_key(payload: McHarnessCaptainKeyRequest):
    if _captain_env_api_key():
        raise HTTPException(
            status_code=409,
            detail="Captain is already configured via environment on this service.",
        )
    _validate_captain_api_key_value(payload.api_key)
    _write_captain_saved_config(payload.api_key, payload.model)
    status = _captain_status_payload()
    return {
        "ok": True,
        "configured": status["configured"],
        "provider": "openrouter",
        "model": status["model"],
        "key_source": status["key_source"],
        "private_key_setup_enabled": status["private_key_setup_enabled"],
        "notes": status["notes"],
    }


@mcharness_router.delete("/captain/key", response_model=McHarnessCaptainKeyResponse, dependencies=[Depends(_require_public_write_access)])
def delete_mcharness_captain_key():
    removed = _delete_captain_saved_config()
    status = _captain_status_payload()
    notes = list(status.get("notes") or [])
    if removed:
        notes.append("Saved Captain key removed.")
    else:
        notes.append("No saved Captain key to remove.")
    return {
        "ok": True,
        "configured": status["configured"],
        "provider": "openrouter",
        "model": status["model"],
        "key_source": status["key_source"],
        "private_key_setup_enabled": status["private_key_setup_enabled"],
        "notes": notes,
    }


def _local_preview_plan(*, goal: str, repo_id: str, lane_id: str) -> dict[str, Any]:
    """Deterministic local plan generator — no cloud tokens, no API key required.

    Produces 3-5 practical steps by parsing intent keywords from the goal.
    Marked source=local_preview so UI can display an honest badge.
    """
    import hashlib

    goal_lower = goal.lower()
    plan_id = "plan_" + hashlib.sha1(f"local:{goal}:{repo_id}".encode()).hexdigest()[:8]

    # Classify intent for step template selection
    is_fix    = any(w in goal_lower for w in ("fix", "bug", "error", "broken", "crash", "fail"))
    is_add    = any(w in goal_lower for w in ("add", "build", "create", "implement", "new", "feat"))
    is_refact = any(w in goal_lower for w in ("refactor", "clean", "simplify", "rename", "move", "reorganize"))
    is_test   = any(w in goal_lower for w in ("test", "spec", "coverage", "pytest", "playwright"))
    is_docs   = any(w in goal_lower for w in ("doc", "readme", "comment", "explain"))
    is_ui     = any(w in goal_lower for w in ("ui", "style", "css", "html", "button", "modal", "page"))

    g = goal[:80]
    r = repo_id

    if is_fix:
        steps = [
            {"id": "step_1", "title": "Reproduce the issue", "prompt": f"In {r}: reproduce the bug described in '{g}'. Read the relevant file(s), identify the failing code path, and write down the exact error or wrong behaviour. Do not edit yet."},
            {"id": "step_2", "title": "Identify root cause", "prompt": f"In {r}: trace the root cause of '{g}'. List the file(s) and line(s) involved. Confirm the fix scope before editing."},
            {"id": "step_3", "title": "Apply minimal fix", "prompt": f"In {r}: apply the smallest correct fix for '{g}'. Edit only the identified lines. Do not refactor surrounding code."},
            {"id": "step_4", "title": "Run tests and verify", "prompt": f"In {r}: run the relevant tests for the fix to '{g}'. Confirm passing. If tests fail, diagnose before retrying."},
        ]
    elif is_ui:
        steps = [
            {"id": "step_1", "title": "Audit current UI", "prompt": f"In {r}: read the relevant HTML/CSS/JS for '{g}'. List what needs to change. Do not edit yet."},
            {"id": "step_2", "title": "Apply UI changes", "prompt": f"In {r}: implement the UI changes for '{g}'. Edit only the relevant web files. Keep it minimal."},
            {"id": "step_3", "title": "Verify in browser", "prompt": f"In {r}: verify the UI change for '{g}' loads correctly. Check for console errors. Note any visual issues."},
        ]
    elif is_test:
        steps = [
            {"id": "step_1", "title": "Identify test gaps", "prompt": f"In {r}: review existing tests related to '{g}'. List what is missing or uncovered."},
            {"id": "step_2", "title": "Write new tests", "prompt": f"In {r}: write the new tests for '{g}'. Follow the existing test style. Do not modify production code."},
            {"id": "step_3", "title": "Run and confirm", "prompt": f"In {r}: run the new tests for '{g}'. Confirm all pass. Fix any test setup issues."},
        ]
    elif is_docs:
        steps = [
            {"id": "step_1", "title": "Read existing docs", "prompt": f"In {r}: read the existing documentation relevant to '{g}'. List what is outdated or missing."},
            {"id": "step_2", "title": "Write documentation", "prompt": f"In {r}: write or update the documentation for '{g}'. Be concise and accurate. Do not add padding."},
        ]
    elif is_refact:
        steps = [
            {"id": "step_1", "title": "Audit target code", "prompt": f"In {r}: read the code to be refactored for '{g}'. List what changes are needed. Do not edit yet."},
            {"id": "step_2", "title": "Refactor", "prompt": f"In {r}: apply the refactor for '{g}'. Preserve all existing behaviour. Run tests after each file changed."},
            {"id": "step_3", "title": "Verify no regressions", "prompt": f"In {r}: run the full relevant test suite after refactoring '{g}'. Confirm no regressions."},
        ]
    else:
        # Generic add/build/default
        steps = [
            {"id": "step_1", "title": "Inspect current state", "prompt": f"In {r}: read the relevant files for '{g}'. Understand the current structure. Do not edit yet."},
            {"id": "step_2", "title": "Implement", "prompt": f"In {r}: implement '{g}'. Follow existing patterns. Make minimal, focused changes."},
            {"id": "step_3", "title": "Test and verify", "prompt": f"In {r}: run relevant tests after implementing '{g}'. Confirm expected behaviour. Fix any issues before moving on."},
            {"id": "step_4", "title": "Review and clean up", "prompt": f"In {r}: review the changes for '{g}'. Remove debug code, fix obvious style issues, ensure nothing is broken."},
        ]

    for step in steps:
        step["agent"] = lane_id
        step["status"] = "queued"
        step["recommended_agent"] = lane_id

    return {
        "ok": True,
        "plan_id": plan_id,
        "title": f"Plan: {goal[:60]}",
        "summary": f"Local preview plan for: {goal}",
        "goal": goal,
        "repo_id": repo_id,
        "lane_id": lane_id,
        "source": "local_preview",
        "steps": steps,
        "status": "active",
        "notes": ["Local preview plan — no cloud tokens used. Set OPENROUTER_API_KEY for AI-generated plans."],
    }


def _write_plan_memory(*, plan: dict[str, Any], goal: str, repo_id: str, lane_id: str) -> Optional[str]:
    """Write a Warden memory after a plan is created. Returns memory_id or None."""
    try:
        from .workbench import WorkbenchStore, WorkbenchMemoryCreateRequest
        store = WorkbenchStore()
        steps = plan.get("steps") or []
        step_lines = "\n".join(
            f"  {i+1}. {s.get('title','?')} ({s.get('agent','?')})"
            for i, s in enumerate(steps)
        )
        source = plan.get("source", "real_captain")
        summary = f"Captain created a {'local preview ' if source == 'local_preview' else ''}plan for: {goal[:80]}"
        content = f"Plan: {plan.get('title','')}\n{plan.get('summary','')}\n\nSteps:\n{step_lines}"
        plan_id = plan.get("plan_id", "")
        import hashlib
        mem_id = "captain-plan-" + hashlib.sha1(plan_id.encode()).hexdigest()[:12]
        existing = store.search_memories(mem_id, limit=1)
        if any(m.memory_id == mem_id for m in existing):
            return mem_id
        store.create_memory(WorkbenchMemoryCreateRequest(
            memory_id=mem_id,
            scope="warden",
            summary=summary,
            source="captain",
            title=summary[:80],
            kind="decision",
            tags=["captain", "plan", source, lane_id],
            metadata={
                "plan_id": plan_id,
                "goal": goal,
                "repo_id": repo_id,
                "lane_id": lane_id,
                "step_count": len(steps),
                "source": source,
                "content": content,
            },
        ))
        return mem_id
    except Exception:
        return None


def _write_dispatch_memory(
    *,
    kind: str,
    plan_id: str,
    step_id: str,
    step_title: str,
    run_id: str,
    repo_id: str,
    lane_id: str,
    goal: str,
    reason: str = "",
    transcript_excerpt: str = "",
) -> Optional[str]:
    """Write a blocked_attempt or agent_result memory after a dispatch attempt. Returns memory_id or None."""
    try:
        import hashlib
        from . import workbench as _wb
        from .workbench import WorkbenchStore, WorkbenchMemoryCreateRequest
        store = WorkbenchStore(root=_wb.WORKBENCH_ROOT)
        mem_id = "dispatch-" + hashlib.sha1(f"{plan_id}:{step_id}:{run_id}".encode()).hexdigest()[:12]
        if kind == "blocked_attempt":
            summary = (
                f"Captain dispatch blocked — runner unavailable. "
                f"Step: {step_title[:60]} (plan {plan_id[:12]}, step {step_id})"
            )
        else:
            summary = (
                f"Captain dispatched step: {step_title[:60]} "
                f"(plan {plan_id[:12]}, step {step_id}, run {run_id[:12]})"
            )
        content_lines = [
            f"kind: {kind}",
            f"plan_id: {plan_id}",
            f"step_id: {step_id}",
            f"step_title: {step_title}",
            f"run_id: {run_id}",
            f"repo_id: {repo_id}",
            f"lane_id: {lane_id}",
            f"goal: {goal[:120]}",
        ]
        if reason:
            content_lines.append(f"reason: {reason}")
        if transcript_excerpt:
            content_lines.append(f"transcript_excerpt: {transcript_excerpt[:400]}")
        store.create_memory(WorkbenchMemoryCreateRequest(
            memory_id=mem_id,
            scope="warden",
            summary=summary,
            source="captain_dispatch",
            title=summary[:80],
            kind=kind,
            tags=["captain", "dispatch", kind, lane_id, repo_id],
            metadata={
                "plan_id": plan_id,
                "step_id": step_id,
                "step_title": step_title,
                "run_id": run_id,
                "repo_id": repo_id,
                "lane_id": lane_id,
                "goal": goal[:120],
                "reason": reason,
                "kind": kind,
            },
        ))
        return mem_id
    except Exception:
        return None


@mcharness_router.post("/captain/plan", response_model=McHarnessCaptainPlanResponse)
def create_mcharness_captain_plan(payload: McHarnessCaptainPlanRequest):
    # Resolve repo — fail hard on unknown repo when cloud key present (real planning needs valid path)
    # fall back gracefully when local preview only
    has_cloud_key = bool(_captain_api_key())
    try:
        repo_path, repo = _resolve_allowlisted_repo(payload.repo_id)
    except HTTPException:
        if has_cloud_key:
            raise
        repo = {"repo_id": payload.repo_id or "mcharness-public-export",
                "path": str(SAFE_REPO_PATHS[1] if len(SAFE_REPO_PATHS) > 1 else SAFE_REPO_PATHS[0])}

    lane_id = payload.lane_id or "codex_cli"

    # Try cloud captain first; fall back to local preview
    if _captain_api_key():
        try:
            agent = _resolve_captain_plan_agent(lane_id)
            resolved_lane = str(agent.get("lane_id") or BUILTIN_CODEX_ID)
            _validate_agent_lane(resolved_lane)
            plan, notes = _build_captain_plan(goal=payload.goal, repo=repo, lane_id=resolved_lane)
            plan["source"] = "real_captain"
        except HTTPException:
            raise
        except Exception as exc:
            plan = _local_preview_plan(goal=payload.goal, repo_id=repo["repo_id"], lane_id=lane_id)
            notes = plan.get("notes", []) + [f"Cloud planning failed: {exc}"]
            plan["notes"] = notes
    else:
        plan = _local_preview_plan(goal=payload.goal, repo_id=repo["repo_id"], lane_id=lane_id)
        notes = plan.get("notes", [])

    # Persist plan (best-effort — don't fail the response if write fails)
    persisted = None
    try:
        persisted = persist_plan(MCTABLE_ROOT, goal=payload.goal, repo_id=repo["repo_id"], plan_data=plan)
    except Exception:
        persisted = plan

    # Write memory (best-effort)
    _write_plan_memory(goal=payload.goal, plan=plan, repo_id=repo["repo_id"], lane_id=lane_id)

    response = _captain_plan_response(persisted, notes=notes)
    response["source"] = plan.get("source", "local_preview")
    return response


@mcharness_router.get("/captain/plans/recent")
def get_mcharness_captain_plans_recent():
    # Plans are always readable — no runner required
    try:
        plans = list_recent_plans(MCTABLE_ROOT)
    except Exception:
        plans = []
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "plans": [_captain_plan_response(plan) for plan in plans],
    }


@mcharness_router.get("/captain/plans/{plan_id}")
def get_mcharness_captain_plan_detail(plan_id: str):
    if not _run_history_read_enabled():
        plan = get_plan_record(MCTABLE_ROOT, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
        return {
            "service": "mcharness-control-plane",
            "service_mode": _service_mode_label(),
            "plan": _captain_plan_response(sanitize_plan_public(plan)),
        }
    plan = get_plan_detail(MCTABLE_ROOT, plan_id, include_prompts=True)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "plan": _captain_plan_response(plan),
    }


@mcharness_router.post("/captain/plans")
def post_mcharness_captain_plan_persist(payload: McHarnessCaptainPlanPersistRequest):
    if not _run_history_write_enabled():
        raise HTTPException(status_code=403, detail="Captain plan writes require the private runner service.")
    plan_data = {
        "plan_id": payload.plan_id,
        "title": payload.title,
        "summary": payload.summary,
        "steps": payload.steps,
    }
    persisted = persist_plan(MCTABLE_ROOT, goal=payload.goal, repo_id=payload.repo_id, plan_data=plan_data)
    return {
        "ok": True,
        "plan": _captain_plan_response(persisted),
    }


@mcharness_router.post("/captain/plans/{plan_id}/steps/{step_id}/dispatch")
def post_mcharness_captain_plan_step_dispatch(plan_id: str, step_id: str):
    """Dispatch a Captain plan step to the local runner.

    Always succeeds: when the runner is unavailable, saves a blocked_attempt
    memory and returns blocked=True instead of raising 403.
    """
    plan = get_plan_record(MCTABLE_ROOT, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    if plan.get("current_step_id") != step_id:
        raise HTTPException(status_code=409, detail="Only the current Captain step can be dispatched.")
    step = next((item for item in plan.get("steps") or [] if item.get("step_id") == step_id), None)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Captain plan step not found: {step_id}")
    repo_id = str(plan.get("repo_id") or "")
    if not repo_id:
        raise HTTPException(status_code=400, detail="Captain plan is missing repo_id.")

    step_title = str(step.get("title") or plan.get("title") or "Captain step")
    prompt = str(step.get("prompt") or "")
    goal = str(plan.get("goal") or plan.get("title") or "")
    lane_id = "codex_cli"

    # Blocked path: runner not available — save honest blocked_attempt memory
    if not _codex_runner_ready():
        import uuid
        run_id = "blocked-" + str(uuid.uuid4())[:8]
        create_run_record(
            MCTABLE_ROOT,
            run_id=run_id,
            title=f"[blocked] {step_title}",
            agent_id="codex_cli",
            agent_adapter="codex_cli",
            repo_id=repo_id,
            branch=None,
            prompt=prompt,
            status="blocked",
            plan_id=plan_id,
            created_by="captain_dispatch",
            service_mode="public",
        )
        mem_id = _write_dispatch_memory(
            kind="blocked_attempt",
            plan_id=plan_id,
            step_id=step_id,
            step_title=step_title,
            run_id=run_id,
            repo_id=repo_id,
            lane_id=lane_id,
            goal=goal,
            reason="runner_unavailable",
        )
        return {
            "ok": True,
            "blocked": True,
            "service": "mcharness-control-plane",
            "run_id": run_id,
            "memory_id": mem_id,
            "message": "Runner unavailable — blocked attempt saved to Memory",
            "plan": _captain_plan_response(plan),
            "dispatch": {},
        }

    # Happy path: runner ready — dispatch and write agent_result memory
    dispatch = _execute_codex_dispatch_for_step(
        title=step_title,
        prompt=prompt,
        repo_id=repo_id,
        plan_id=plan_id,
        step_id=step_id,
    )
    runner_id = str(dispatch.get("runner_id") or "")
    updated = mark_step_dispatched(
        MCTABLE_ROOT,
        plan_id,
        step_id,
        run_id=runner_id,
        status="dispatched",
    )
    mem_id = _write_dispatch_memory(
        kind="agent_result",
        plan_id=plan_id,
        step_id=step_id,
        step_title=step_title,
        run_id=runner_id,
        repo_id=repo_id,
        lane_id=lane_id,
        goal=goal,
    )
    resp = {
        "ok": True,
        "blocked": False,
        "service": "mcharness-control-plane",
        "run_id": runner_id,
        "memory_id": mem_id,
        "plan": _captain_plan_response(updated),
        "dispatch": dispatch,
    }
    return resp


@mcharness_router.post("/captain/plans/{plan_id}/steps/{step_id}/complete", dependencies=[Depends(_require_run_history_write)])
def post_mcharness_captain_plan_step_complete(plan_id: str, step_id: str, payload: McHarnessCaptainStepCompleteRequest):
    plan = get_plan_record(MCTABLE_ROOT, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Captain plan not found: {plan_id}")
    step = next((item for item in plan.get("steps") or [] if item.get("step_id") == step_id), None)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Captain plan step not found: {step_id}")
    if step.get("run_id"):
        assert_step_completion_allowed(MCTABLE_ROOT, str(step["run_id"]))
    updated = complete_captain_plan_step(
        MCTABLE_ROOT,
        plan_id,
        step_id,
        evidence_ids=list(payload.evidence_ids or []),
    )
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "plan": _captain_plan_response(updated),
    }


@mcharness_router.post("/captain/plans/{plan_id}/steps/{step_id}/revise", dependencies=[Depends(_require_run_history_write)])
def post_mcharness_captain_plan_step_revise(plan_id: str, step_id: str, payload: McHarnessCaptainStepReviseRequest):
    updated = revise_captain_plan_step(
        MCTABLE_ROOT,
        plan_id,
        step_id,
        title=payload.title,
        prompt=payload.prompt,
        note=payload.note,
    )
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "plan": _captain_plan_response(updated),
    }


@mcharness_router.post("/captain/plans/{plan_id}/stop", dependencies=[Depends(_require_run_history_write)])
def post_mcharness_captain_plan_stop(plan_id: str, payload: McHarnessCaptainPlanStopRequest):
    updated = stop_captain_plan(MCTABLE_ROOT, plan_id, note=payload.note)
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "plan": _captain_plan_response(updated),
    }

@router.get("/tasks", response_model=List[TaskState])
def get_tasks():
    tasks = []
    if TASKS_DIR.exists():
        graph = McTableTaskGraph()
        for p in TASKS_DIR.glob("*.json"):
            try:
                task_id = p.stem
                tasks.append(graph.load_state(task_id))
            except Exception:
                pass
    return tasks

@router.post("/tasks", response_model=TaskState, dependencies=[Depends(_require_public_write_access)])
def create_task(req: TaskCreateRequest):
    if req.command not in ALLOWED_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Command '{req.command}' is not allowlisted.")

    # Check if task already exists
    if (TASKS_DIR / f"{req.task_id}.json").exists():
        raise HTTPException(status_code=400, detail=f"Task {req.task_id} already exists.")

    graph = McTableTaskGraph()
    graph.create_task(req.task_id, req.title, req.description, req.command, req.args)
    return graph.drive_task_to_review(req.task_id)

@router.get("/tasks/{task_id}", response_model=TaskState)
def get_task(task_id: str):
    graph = McTableTaskGraph()
    try:
        return graph.load_state(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

@router.get("/tasks/{task_id}/events")
def get_task_events(task_id: str):
    graph = McTableTaskGraph()
    try:
        state = graph.load_state(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

    # Return a simple list of events based on the task state
    return [
        {"event": "task_created", "timestamp": state.created_at.isoformat()},
        {"event": "step_executed", "step": state.current_step, "timestamp": state.updated_at.isoformat()}
    ]

@router.post("/tasks/{task_id}/decision", response_model=TaskState, dependencies=[Depends(_require_public_write_access)])
def post_task_decision(task_id: str, req: DecisionRequest):
    graph = McTableTaskGraph()
    try:
        graph.load_state(task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")
    return graph.resume_task(
        task_id=task_id,
        decision=req.decision,
        actor=req.actor,
        reviewer_note=req.reviewer_note,
        state_patch=req.state_patch,
    )

@router.get("/worker-runs/{run_id}", response_model=WorkerRun)
def get_worker_run(run_id: str):
    try:
        return WorkerStub.get_status(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Worker run {run_id} not found.")

@router.get("/worker-runs/{run_id}/logs")
def get_worker_run_logs(run_id: str):
    try:
        logs_iterator = WorkerStub.stream_logs(run_id)
        return {"logs": "".join(list(logs_iterator))}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Worker run {run_id} not found.")

@router.post("/worker-runs/{run_id}/cancel", dependencies=[Depends(_require_public_write_access)])
def cancel_worker_run(run_id: str):
    try:
        WorkerStub.cancel_run(run_id)
        return {"status": "cancelled", "run_id": run_id}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Worker run {run_id} not found.")

@router.get("/agents")
def get_agents():
    return [
        {
            "agent_id": "fake-agent",
            "name": "Fake Agent stub",
            "capabilities": list(ALLOWED_COMMANDS)
        }
    ]


@mcharness_router.get("/repos")
def get_mcharness_repos():
    return {
        "service": "mcharness-control-plane",
        "mode": "server_control_plane",
        "repos": _repo_entries(),
    }


@mcharness_router.get("/agent-lanes")
def get_mcharness_agent_lanes():
    return {
        "service": "mcharness-control-plane",
        "manual_mode": True,
        "lanes": _lane_entries(),
    }


@mcharness_router.get("/agents")
def get_mcharness_agents():
    agents = list_all_agents(
        MCTABLE_ROOT,
        codex_runner_ready=_codex_runner_ready(),
        private_only=_agent_registry_private_only(),
    )
    return {
        "service": "mcharness-control-plane",
        "registry_write_enabled": _agent_registry_write_enabled(),
        "agents": [sanitize_agent_profile(agent) for agent in agents],
    }

# --- Marius Agent Wrapper Endpoints ---

@mcharness_router.get("/agents/marius/status")
def get_marius_agent_status():
    try:
        from src.marius.api import status as marius_status
        return {"ok": True, "data": marius_status()}
    except ImportError:
        raise HTTPException(status_code=404, detail="Marius not installed")

@mcharness_router.post("/agents/marius/chat")
async def marius_agent_chat(request: Request):
    try:
        from src.marius.api import chat as marius_chat, ChatRequest
        payload = await request.json()
        chat_req = ChatRequest(**payload)
        res = await marius_chat(chat_req)
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcharness_router.get("/agents/marius/models")
async def get_marius_agent_models():
    try:
        from src.marius.api import get_models
        res = await get_models()
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcharness_router.post("/agents/marius/model/set")
async def set_marius_agent_model(request: Request):
    try:
        from src.marius.api import set_model, ModelRequest
        payload = await request.json()
        req = ModelRequest(**payload)
        res = await set_model(req)
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcharness_router.post("/agents/marius/model/profile")
async def set_marius_agent_profile(request: Request):
    try:
        from src.marius.api import set_profile, ProfileRequest
        payload = await request.json()
        req = ProfileRequest(**payload)
        res = await set_profile(req)
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcharness_router.post("/agents/marius/model/bench")
async def bench_marius_agent_model(request: Request):
    try:
        from src.marius.api import run_benchmark
        payload = await request.json()
        res = await run_benchmark(payload)
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcharness_router.get("/agents/marius/context")
async def get_marius_agent_context():
    try:
        from src.marius.api import get_context
        res = await get_context()
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcharness_router.get("/agents/marius/memory/recall")
def get_marius_agent_memory_recall(q: str):
    try:
        from src.marius.api import recall as marius_recall
        res = marius_recall(q)
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@mcharness_router.post("/agents/marius/memory/remember")
async def post_marius_agent_memory_remember(request: Request):
    try:
        from src.marius.api import remember as marius_remember, MemoryRequest
        payload = await request.json()
        req = MemoryRequest(**payload)
        res = marius_remember(req)
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcharness_router.get("/memory/health")
def get_warden_memory_health():
    from src.warden.brain_vector_store import count as vec_count
    vec = 0
    try:
        vec = vec_count()
    except Exception:
        pass
    memories = WORKBENCH_STORE.list_memories()
    active = [m for m in memories if m.status != "forgotten"]
    kinds: dict = {}
    for m in active:
        kinds[m.kind] = kinds.get(m.kind, 0) + 1
    return {
        "ok": True,
        "status": "online",
        "memory_count": len(active),
        "total_count": len(memories),
        "vector_count": vec,
        "kinds": kinds,
    }


@mcharness_router.get("/memories")
def get_warden_memories(limit: int = 200, kind: Optional[str] = None, scope: Optional[str] = None):
    memories = WORKBENCH_STORE.list_memories()
    active = [m for m in memories if m.status != "forgotten"]
    if kind:
        active = [m for m in active if m.kind == kind]
    if scope:
        active = [m for m in active if (m.project_id or m.scope or "").lower() == scope.lower()]
    active.sort(key=lambda m: m.updated_at, reverse=True)
    active = active[:max(1, min(limit, 500))]
    return {
        "ok": True,
        "count": len(active),
        "memories": [memory.model_dump(mode="json") for memory in active],
    }


@mcharness_router.get("/memories/search")
@mcharness_router.get("/memories/recall")
def recall_warden_memories(q: str = "", scope: Optional[str] = None, kind: Optional[str] = None, limit: int = 20):
    memories = WORKBENCH_STORE.search_memories(q, scope=scope, limit=max(1, min(limit, 100)))
    if kind:
        memories = [m for m in memories if m.kind == kind]
    return {
        "ok": True,
        "query": q,
        "scope": scope,
        "count": len(memories),
        "memories": [memory.model_dump(mode="json") for memory in memories],
    }


@mcharness_router.post("/memory/recall")
def post_recall_warden_memories(payload: WardenMemoryRecallRequest):
    return recall_warden_memories(payload.query, scope=payload.project_id, limit=payload.limit)


class MemoryPatchRequest(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    confidence: Optional[float] = None


@mcharness_router.patch("/memories/{memory_id}")
def patch_warden_memory(memory_id: str, payload: MemoryPatchRequest):
    path = WORKBENCH_STORE._path("memories", memory_id)
    if not path.exists():
        raise HTTPException(404, f"Memory not found: {memory_id}")
    from src.warden.workbench import WorkbenchMemory, _atomic_write_json, _now
    memory = WorkbenchMemory(**json.loads(path.read_text()))
    if payload.status is not None:
        memory.status = payload.status
    if payload.title is not None:
        memory.title = payload.title
    if payload.summary is not None:
        memory.summary = payload.summary
    if payload.tags is not None:
        memory.tags = payload.tags
    if payload.notes is not None:
        memory.notes = payload.notes
    if payload.confidence is not None:
        memory.confidence = payload.confidence
    memory.updated_at = _now()
    _atomic_write_json(path, memory.model_dump(mode="json"))
    return {"ok": True, "memory": memory.model_dump(mode="json")}


@mcharness_router.post("/memories")
def create_warden_memory(payload: WorkbenchMemoryCreateRequest):
    try:
        memory = WORKBENCH_STORE.create_memory(payload)
        return {"ok": True, "memory": memory.model_dump(mode="json")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcharness_router.post("/memories/remember")
@mcharness_router.post("/memory/remember")
async def remember_warden_memory(request: Request):
    try:
        payload = await request.json()
        if not payload.get("content"):
            payload["content"] = payload.get("summary") or payload.get("note") or ""
        req = WorkbenchMemoryRememberRequest(**payload)
        memory = WORKBENCH_STORE.remember_memory(req)
        return {"ok": True, "memory": memory.model_dump(mode="json")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcharness_router.post("/memory/context-pack", dependencies=[Depends(_require_private_memory_access)])
def post_warden_memory_context_pack(payload: WardenMemoryContextPackRequest):
    if payload.repo_path and ("\x00" in payload.repo_path or "\n" in payload.repo_path):
        raise HTTPException(status_code=400, detail="Invalid repo_path metadata.")
    try:
        return {
            "ok": True,
            **WORKBENCH_STORE.build_memory_context_pack(
                project_id=payload.project_id,
                repo_path=payload.repo_path,
                agent=payload.agent,
                user_prompt=payload.prompt,
                branch=payload.branch,
                task_id=payload.task_id,
                max_memories=payload.max_memories,
                max_chars=payload.max_chars,
            ),
        }
    except Exception:
        raise HTTPException(status_code=503, detail="Warden Memory context is unavailable.")


@mcharness_router.post("/agents/marius/handoff/agent-prompt")
async def post_marius_agent_handoff(request: Request):
    try:
        from src.marius.api import handoff as marius_handoff, HandoffRequest
        payload = await request.json()
        req = HandoffRequest(**payload)
        res = marius_handoff(req)
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- End Marius Wrapper ---

@mcharness_router.get("/agents/templates")
def get_mcharness_agent_templates():
    return {
        "service": "mcharness-control-plane",
        "templates": agent_templates(),
    }


@mcharness_router.post("/agents/test-config", dependencies=[Depends(_require_public_write_access)])
def test_mcharness_agent_config(payload: McHarnessAgentTestConfigRequest):
    if not _agent_registry_write_enabled():
        raise HTTPException(
            status_code=403,
            detail="Agent configuration is available only on the private runner service.",
        )
    return test_agent_config(payload)


@mcharness_router.post("/agents", dependencies=[Depends(_require_public_write_access)])
def create_mcharness_agent(payload: McHarnessAgentCreateRequest):
    if not _agent_registry_write_enabled():
        raise HTTPException(
            status_code=403,
            detail="Agent registration is available only on the private runner service.",
        )
    agent = create_registered_agent(MCTABLE_ROOT, payload)
    return {
        "ok": True,
        "agent": sanitize_agent_profile(
            get_agent_by_id(
                MCTABLE_ROOT,
                agent["id"],
                codex_runner_ready=_codex_runner_ready(),
                private_only=_agent_registry_private_only(),
            )
            or agent
        ),
    }


@mcharness_router.patch("/agents/{agent_id}/config", dependencies=[Depends(_require_public_write_access)])
def patch_mcharness_agent_config(agent_id: str, payload: McHarnessAgentConfigPatchRequest):
    if not _agent_registry_write_enabled():
        raise HTTPException(
            status_code=403,
            detail="Agent configuration is available only on the private runner service.",
        )
    agent = update_registered_agent_config(MCTABLE_ROOT, agent_id, payload)
    return {
        "ok": True,
        "agent": sanitize_agent_profile(
            get_agent_by_id(
                MCTABLE_ROOT,
                agent_id,
                codex_runner_ready=_codex_runner_ready(),
                private_only=_agent_registry_private_only(),
            )
            or agent
        ),
    }


@mcharness_router.patch("/agents/{agent_id}", dependencies=[Depends(_require_public_write_access)])
def patch_mcharness_agent(agent_id: str, payload: McHarnessAgentPatchRequest):
    if not _agent_registry_write_enabled():
        raise HTTPException(
            status_code=403,
            detail="Agent registration is available only on the private runner service.",
        )
    agent = update_registered_agent(MCTABLE_ROOT, agent_id, payload)
    return {
        "ok": True,
        "agent": sanitize_agent_profile(
            get_agent_by_id(
                MCTABLE_ROOT,
                agent_id,
                codex_runner_ready=_codex_runner_ready(),
                private_only=_agent_registry_private_only(),
            )
            or agent
        ),
    }


@mcharness_router.delete("/agents/{agent_id}", dependencies=[Depends(_require_public_write_access)])
def delete_mcharness_agent(agent_id: str):
    if not _agent_registry_write_enabled():
        raise HTTPException(
            status_code=403,
            detail="Agent registration is available only on the private runner service.",
        )
    return delete_registered_agent(MCTABLE_ROOT, agent_id)


@mcharness_router.get("/agents/{agent_id}/status")
def get_mcharness_agent_status(agent_id: str):
    agent = get_agent_by_id(
        MCTABLE_ROOT,
        agent_id,
        codex_runner_ready=_codex_runner_ready(),
        private_only=_agent_registry_private_only(),
    )
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return agent_status_payload(
        agent,
        codex_runner_ready=_codex_runner_ready(),
        root=MCTABLE_ROOT,
        probe_codex=_codex_probe_payload if agent.get("adapter") == "codex_cli" else None,
    )


@mcharness_router.post("/agents/refresh-status")
def refresh_mcharness_agent_statuses():
    agents = refresh_agent_statuses(
        MCTABLE_ROOT,
        codex_runner_ready=_codex_runner_ready(),
        private_only=_agent_registry_private_only(),
        probe_codex=_codex_probe_payload,
    )
    last_checked_at = max((agent.get("last_checked_at") or "" for agent in agents), default=None)
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "registry_write_enabled": _agent_registry_write_enabled(),
        "last_checked_at": last_checked_at,
        "agents": agents,
        "notes": ["Status refresh probes agents only. No tasks were started."],
    }


@mcharness_router.post("/agents/{agent_id}/probe")
def probe_mcharness_agent(agent_id: str):
    agent = get_agent_by_id(
        MCTABLE_ROOT,
        agent_id,
        codex_runner_ready=_codex_runner_ready(),
        private_only=_agent_registry_private_only(),
    )
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return probe_agent(
        agent,
        codex_runner_ready=_codex_runner_ready(),
        root=MCTABLE_ROOT,
        probe_codex=_codex_probe_payload if agent.get("adapter") == "codex_cli" else None,
    )


@mcharness_router.post("/sessions")
def create_mcharness_session(payload: McHarnessSessionCreateRequest):
    repo_path = _validate_repo_path(payload.repo_path)
    lane = _validate_agent_lane(payload.agent_lane)
    thread = WORKBENCH_STORE.create_thread(
        WorkbenchThreadCreateRequest(
            title=payload.title,
            goal=payload.objective,
            metadata={
                "repo_path": str(repo_path),
                "agent_lane": lane["lane_id"],
                "server_host_mode": True,
                "fake_or_manual_mode": True,
            },
        )
    )
    captain = create_captain_state_machine_run(thread["thread_id"], payload.objective).model_dump(mode="json")
    _append_run_event(captain["run_id"], "Session created", f"Server control plane created session for {repo_path}.", "info", "note")
    plan_captain_run(captain["captain_run_id"], CaptainPlanRequest(instruction=payload.plan_instruction))
    queue_captain_run(captain["captain_run_id"])
    assign_captain_minions(captain["captain_run_id"])
    thread = WORKBENCH_STORE.get_thread(thread["thread_id"])
    run = _run_for_session(thread["thread_id"])
    git_snapshot = _capture_git_status_artifacts(thread)
    run_summary = _create_run_summary_artifact(thread, run, "Session initialized in server control-plane mode.")
    return {
        "session_id": thread["thread_id"],
        "thread": thread,
        "run": run,
        "captain_run_id": captain["captain_run_id"],
        "repo_path": str(repo_path),
        "agent_lane": lane["lane_id"],
        "git_snapshot": git_snapshot,
        "run_summary_artifact": run_summary,
    }


@mcharness_router.post("/sessions/{session_id}/queue")
def queue_mcharness_prompt(session_id: str, payload: McHarnessQueueRequest):
    run = _run_for_session(session_id)
    state = add_captain_queue_item(
        run["run_id"],
        CaptainQueueItemCreateRequest(
            title=payload.title,
            prompt=payload.prompt,
            target_role=payload.target_role,
            file_scope=list(payload.file_scope),
            forbidden_file_scope=list(payload.forbidden_file_scope),
            evidence_required=list(payload.evidence_required),
            acceptance_checks=list(payload.acceptance_checks),
            export_format="generic_markdown",
        ),
    ).model_dump(mode="json")
    _append_run_event(run["run_id"], "Prompt queued", f"Queued prompt {payload.title}.", "info", "instruction")
    queue_item_id = None
    prompt_queue = state.get("prompt_queue") if isinstance(state, dict) else getattr(state, "prompt_queue", None)
    if prompt_queue:
        latest = prompt_queue[-1]
        queue_item_id = latest.get("queue_item_id") if isinstance(latest, dict) else getattr(latest, "queue_item_id", None)
    return {
        "session_id": session_id,
        "run_id": run["run_id"],
        "queue_item_id": queue_item_id,
        "state": state,
    }


@mcharness_router.post("/sessions/{session_id}/prompt-export")
def export_mcharness_prompt(session_id: str, payload: McHarnessPromptExportRequest):
    run = _run_for_session(session_id)
    thread = _thread_for_session(session_id)
    prompt_text = export_captain_queue_item(payload.queue_item_id)
    artifact = _create_artifact(
        thread["thread_id"],
        "prompt_export",
        f"Prompt export {payload.queue_item_id}",
        prompt_text,
        f"Prompt export for {payload.queue_item_id}",
        "md",
    )
    if payload.mark_sent:
        _append_run_event(run["run_id"], "Prompt marked sent", f"Marked {payload.queue_item_id} as sent to the selected CLI lane.", "info", "artifact")
    return {
        "session_id": session_id,
        "run_id": run["run_id"],
        "queue_item_id": payload.queue_item_id,
        "prompt_text": prompt_text,
        "artifact": artifact,
    }


@mcharness_router.post("/sessions/{session_id}/runner-intent")
def post_mcharness_runner_intent(session_id: str, payload: McHarnessRunnerIntentRequest):
    """Dry-run only preview. Computes would-be command, prompt/transcript paths, safety policy.
    Never executes any CLI, never starts tmux, never touches secrets. Rejects non-dry and unknown ids.
    """
    if payload.mode != "dry_run":
        raise HTTPException(status_code=400, detail="Only dry_run mode is supported. Real execution is disabled by policy.")

    # Validate lane (known only; allow manual + implemented; reject unknown. Placeholders will show disabled.)
    lane = next((entry for entry in AGENT_LANES if entry["lane_id"] == payload.lane_id), None)
    if lane is None:
        raise HTTPException(status_code=400, detail=f"Unknown agent lane: {payload.lane_id}")

    # Validate repo by id (name or full path match on allowlist only)
    repo_path: Optional[Path] = None
    for p in SAFE_REPO_PATHS:
        if p.name == payload.repo_id or str(p) == payload.repo_id:
            repo_path = p
            break
    if repo_path is None:
        raise HTTPException(status_code=400, detail=f"Unknown repo_id (must be allowlisted): {payload.repo_id}")

    # Validate session exists (rejects missing/invalid)
    _ = _thread_for_session(session_id)

    cwd = str(repo_path)
    pid = payload.prompt_artifact_id or payload.queue_item_id or "head"
    prompt_file_path = str(ARTIFACT_BODY_ROOT / session_id / f"prompt-{pid}.md")
    transcript_file_path = str(ARTIFACT_BODY_ROOT / session_id / "transcript.txt")

    if payload.lane_id == "manual_paste":
        command_preview = (
            f"MANUAL: cd {cwd} && cat {prompt_file_path}  # run your local CLI in cwd, then POST transcript to /sessions/{session_id}/manual-result"
        )
    elif payload.lane_id == "codex_cli":
        command_preview = f"codex exec --cd {cwd} --output-last-message {transcript_file_path} < {prompt_file_path}  # (gated real; requires MCHARNESS_*_RUNNER_ENABLED=true for both tmux+codex; non-int or tmux attach)"
    elif payload.lane_id == "agy_cli":
        command_preview = f"agy --prompt {prompt_file_path}  # (dry-run preview only; cwd={cwd}; real launch disabled)"
    else:
        command_preview = f"# {payload.lane_id} would read {prompt_file_path} (placeholder lane; controlled_run_disabled)"

    safety_policy = {
        "allowlisted_lane": True,
        "allowlisted_repo": True,
        "arbitrary_shell_disabled": True,
        "public_real_agent_launch_disabled": True,
        "tmux_runner_enabled": _tmux_runner_enabled(),
    }
    notes = [
        "dry_run preview only. No CLI subprocess, no tmux session, no secret inspection, no network to providers.",
        "Controlled runner (real execution) is disabled in this public cockpit.",
    ]

    resp = {
        "ok": True,
        "real_execution_enabled": False,
        "lane_id": payload.lane_id,
        "repo_id": payload.repo_id,
        "session_id": session_id,
        "cwd": cwd,
        "prompt_file_path": prompt_file_path,
        "transcript_file_path": transcript_file_path,
        "command_preview": command_preview,
        "safety_policy": safety_policy,
        "notes": notes,
    }

    # May persist a runner_intent artifact (safe, read-oriented preview)
    try:
        _create_artifact(
            session_id,
            "runner_intent",
            f"runner-intent-{payload.lane_id}",
            json.dumps(resp, indent=2),
            "Dry-run runner intent preview (no execution performed)",
            "json",
        )
    except Exception:
        # preview response still valid even if artifact registration skipped
        pass

    return resp


@mcharness_router.post("/sessions/{session_id}/runner/start")
def post_mcharness_runner_start(session_id: str, payload: McHarnessRunnerStartRequest):
    """Start controlled runner for allowlisted lane (only fake_test_lane by default; real disabled).
    Validates session, lane (known), repo (allowlist), uses backend generated paths/names/cmd only.
    """
    thread = _thread_for_session(session_id)
    lane = next((entry for entry in AGENT_LANES if entry["lane_id"] == payload.lane_id), None)
    if lane is None:
        raise HTTPException(status_code=400, detail=f"Unknown agent lane: {payload.lane_id}")

    if payload.lane_id == "codex_cli":
        if not (_tmux_runner_enabled() and _codex_runner_enabled()):
            raise HTTPException(
                status_code=403,
                detail="Controlled Codex runner disabled (requires BOTH MCHARNESS_TMUX_RUNNER_ENABLED=true AND MCHARNESS_CODEX_RUNNER_ENABLED=true). For personal manual smoke only; no automated real Codex.",
            )
        assert_runner_session_capacity(MCTABLE_ROOT, safe_cmd=_safe_cmd, runner_state_root=RUNNER_STATE_ROOT)
    elif payload.lane_id != "fake_test_lane" and not _tmux_runner_enabled():
        raise HTTPException(
            status_code=403,
            detail="Controlled runner disabled (MCHARNESS_TMUX_RUNNER_ENABLED=false). Only fake_test_lane supported for tests/proof.",
        )
    if payload.lane_id != "fake_test_lane" and payload.lane_id != "codex_cli":
        raise HTTPException(status_code=400, detail="Controlled run for this lane not implemented yet (only codex_cli + fake_test_lane).")

    # map repo_id to allowlisted path (id or full)
    repo_path: Optional[Path] = None
    for p in SAFE_REPO_PATHS:
        if p.name == payload.repo_id or str(p) == payload.repo_id:
            repo_path = p
            break
    if repo_path is None:
        raise HTTPException(status_code=400, detail=f"Unknown repo_id (must be allowlisted): {payload.repo_id}")

    title, original_prompt = _resolve_dispatch_prompt(session_id, payload)
    dispatch_prompt, memory_context = build_agent_prompt_with_memory(
        original_prompt,
        project_id=payload.repo_id,
        repo_path=str(repo_path),
        agent=payload.agent_id or payload.lane_id,
        branch=payload.branch,
        task_id=payload.plan_id,
    )
    payload.title = title
    payload.prompt = dispatch_prompt

    runner_id = f"run_{uuid.uuid4().hex[:8]}"
    safe_name = _tmux_session_name(session_id, runner_id)
    pid = payload.prompt_artifact_id or payload.queue_item_id or "head"
    prompt_path = str(ARTIFACT_BODY_ROOT / session_id / f"prompt-{pid}.md")
    trans_path = str(ARTIFACT_BODY_ROOT / session_id / f"transcript-runner-{runner_id}.txt")

    state: dict[str, Any] = {
        "session_id": session_id,
        "runner_id": runner_id,
        "lane_id": payload.lane_id,
        "repo_id": payload.repo_id,
        "queue_item_id": payload.queue_item_id,
        "prompt_artifact_id": payload.prompt_artifact_id,
        "dispatch_prompt": dispatch_prompt,
        "memory_context": memory_context,
        "status": "starting",
        "tmux_session_name": safe_name,
        "prompt_file_path": prompt_path,
        "transcript_file_path": trans_path,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "stopped_at": None,
        "exit_code": None,
        "safety_policy": {
            "allowlisted_lane": True,
            "allowlisted_repo": True,
            "tmux_runner_enabled": _tmux_runner_enabled(),
            "codex_runner_enabled": _codex_runner_enabled() if payload.lane_id == "codex_cli" else False,
            "real_provider": payload.lane_id == "codex_cli",
            "arbitrary_shell_disabled": True,
            "public_real_agent_launch_disabled": True,
        },
        "notes": [f"gated tmux runner; lane={payload.lane_id} (codex real only with both flags; fake for tests)"],
    }
    _save_runner_state(state)

    if payload.lane_id == "codex_cli":
        state = _start_codex_runner(state, str(repo_path))
    else:
        # fake
        state = _start_fake_runner(state)
    _save_runner_state(state)

    warden_run = _create_warden_run_on_dispatch(
        session_id,
        payload,
        runner_id=runner_id,
        transcript_path=trans_path,
        status="dispatched",
        original_prompt=original_prompt,
    )
    if payload.lane_id == "codex_cli":
        prompt_memory_id = _remember_run_memory(
            scope=payload.repo_id,
            content=original_prompt,
            kind="agent_prompt",
            title=f"Agent prompt: {title}",
            source_ref=f"run://{runner_id}",
            repo_path=str(repo_path),
            branch=payload.branch,
            task_id=payload.plan_id,
            agent_id=payload.agent_id or "codex_cli",
            tags=["agent-prompt", "private-runner"],
        )
        state["prompt_memory_id"] = prompt_memory_id
        _save_runner_state(state)

    # event for audit/proof
    try:
        run = _run_for_session(session_id)
        _append_run_event(run["run_id"], "Runner started", f"Started {runner_id} lane={payload.lane_id}", "info", "runner")
    except Exception:
        pass

    if warden_run:
        state["warden_run"] = warden_run
    return state


@mcharness_router.get("/sessions/{session_id}/runner/status")
def get_mcharness_runner_status(session_id: str):
    state = _load_runner_state(session_id)
    if not state:
        return {"status": "disabled", "notes": ["no runner for this session (or never started)"]}
    name = state.get("tmux_session_name")
    if name and state.get("status") in ("running", "starting"):
        has = _safe_cmd(["tmux", "has-session", "-t", name], timeout=1.0)
        if has is None or has.returncode != 0:
            state["status"] = "exited"
            # capture final transcript if not already
            final = _get_tmux_transcript(name)
            if final:
                try:
                    Path(state["transcript_file_path"]).write_text(final, encoding="utf-8")
                except Exception:
                    pass
            _save_runner_state(state)
    return state


@mcharness_router.post("/sessions/{session_id}/runner/stop")
def post_mcharness_runner_stop(session_id: str):
    state = _load_runner_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="No runner state for session")
    name = state.get("tmux_session_name")
    if name:
        _stop_tmux(name)
    state["status"] = "stopped"
    state["stopped_at"] = datetime.now(timezone.utc).isoformat()
    state["notes"].append("stopped by operator")
    _save_runner_state(state)
    _sync_warden_run_from_runner_state(state, status="stopped", completed=True)
    try:
        run = _run_for_session(session_id)
        _append_run_event(run.get("run_id", ""), "Runner stopped", f"Stopped runner {state.get('runner_id')}", "info", "runner")
    except Exception:
        pass
    return state


@mcharness_router.get("/sessions/{session_id}/runner/transcript")
def get_mcharness_runner_transcript(session_id: str):
    state = _load_runner_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="No runner for session")
    text = _runner_transcript_text(state)
    return {
        "session_id": session_id,
        "runner_id": state.get("runner_id"),
        "lane_id": state.get("lane_id"),
        "status": state.get("status"),
        "transcript_path": str(state.get("transcript_file_path", "")),
        "transcript": text,
    }


@mcharness_router.post("/sessions/{session_id}/runner/transcript-to-evidence")
def post_mcharness_runner_transcript_to_evidence(session_id: str):
    """Save current runner transcript as evidence artifact (usable with proof gates)."""
    state = _load_runner_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="No runner for session")
    p = Path(state["transcript_file_path"])
    text = p.read_text(encoding="utf-8") if p.exists() else _get_tmux_transcript(state.get("tmux_session_name", ""))
    if not text:
        text = "(no transcript captured yet)"

    artifact = _create_artifact(
        session_id,
        "runner_transcript",
        f"runner-transcript-{state.get('runner_id')}",
        text,
        "transcript from gated tmux runner",
        "txt",
    )
    # also as evidence for gate flow (consistent with manual-result)
    ev = _create_artifact(
        session_id,
        "evidence",
        "Runner transcript evidence",
        text[:2000] + ("\n... (truncated)" if len(text) > 2000 else ""),
        "Saved runner transcript as evidence",
        "md",
    )
    warden_evidence = None
    if _run_history_write_enabled():
        run_id = state.get("runner_id")
        if not run_id:
            existing = find_run_by_session(MCTABLE_ROOT, session_id)
            run_id = existing.get("run_id") if existing else None
        warden_evidence = create_evidence_record(
            MCTABLE_ROOT,
            run_id=str(run_id) if run_id else None,
            evidence_type="transcript",
            title="Codex transcript snapshot",
            summary="Saved runner transcript as evidence",
            content=text,
            agent_id="codex_cli",
            source="live_monitor" if run_id else "live_monitor_unlinked",
        )
    try:
        run = _run_for_session(session_id)
        _append_run_event(run["run_id"], "Runner transcript to evidence", f"Saved transcript for {state.get('runner_id')} as evidence", "info", "evidence")
    except Exception:
        pass
    return {
        "ok": True,
        "artifact": artifact,
        "evidence_artifact": ev,
        "session_id": session_id,
        "warden_evidence": warden_evidence,
    }


@mcharness_router.post("/sessions/{session_id}/manual-result")
def post_mcharness_manual_result(session_id: str, payload: McHarnessManualResultRequest):
    thread = _thread_for_session(session_id)
    run = _run_for_session(session_id)
    metadata = thread.get("metadata") or {}
    artifacts: list[dict[str, Any]] = []
    transcript_text = payload.transcript or payload.summary
    result_kind = "manual_result" if metadata.get("agent_lane") == "manual_paste" else "cli_transcript"
    artifacts.append(
        _create_artifact(
            thread["thread_id"],
            result_kind,
            "CLI transcript" if result_kind == "cli_transcript" else "Manual result",
            transcript_text,
            payload.summary,
            "md",
        )
    )
    artifacts.append(
        _create_artifact(
            thread["thread_id"],
            "evidence",
            "Evidence record",
            payload.summary + "\n",
            payload.summary,
            "md",
        )
    )
    if payload.git_status:
        artifacts.append(
            _create_artifact(
                thread["thread_id"],
                "git_status",
                "Git status",
                payload.git_status,
                "Manual git status capture",
                "txt",
            )
        )
    if payload.git_diff_summary:
        artifacts.append(
            _create_artifact(
                thread["thread_id"],
                "git_diff_summary",
                "Git diff summary",
                payload.git_diff_summary,
                "Manual git diff summary capture",
                "txt",
            )
        )
    if payload.test_output:
        artifacts.append(
            _create_artifact(
                thread["thread_id"],
                "test_output",
                "Test output",
                payload.test_output,
                "Manual test output capture",
                "txt",
            )
        )
    if payload.assignment_id:
        record_captain_assignment_evidence(
            run["run_id"],
            payload.assignment_id,
            CaptainAssignmentEvidenceRequest(
                evidence_summary=payload.summary if not payload.transcript else f"{payload.summary}\n\nTranscript:\n{payload.transcript}",
                source_ref=payload.source_ref,
                artifact_refs=[artifact["path"] for artifact in artifacts],
                verdict=payload.verdict,
            ),
        )
        if payload.complete_assignment:
            complete_captain_assignment(
                run["run_id"],
                payload.assignment_id,
                CaptainAssignmentCompleteRequest(
                    evidence_summary=payload.summary,
                    output_summary=transcript_text,
                ),
            )
    else:
        WORKBENCH_STORE.add_run_evidence(
            run["run_id"],
            WorkbenchEvidenceRecordCreateRequest(
                title="Manual result evidence",
                summary=payload.summary,
                source_type="manual",
                source_ref=payload.source_ref,
                verdict=payload.verdict,
            ),
        )
    repo_path = str(metadata.get("repo_path") or "")
    scope = Path(repo_path).name if repo_path else "warden"
    if payload.verdict in {"failed", "blocked"}:
        memory_kind = "failure"
        memory_tags = ["failure", payload.verdict]
    elif payload.test_output:
        memory_kind = "test_result"
        memory_tags = ["proof", "test"]
    else:
        memory_kind = "agent_result"
        memory_tags = ["claim", "agent-result"]
    _remember_run_memory(
        scope=scope,
        content=payload.summary,
        kind=memory_kind,
        title=f"Run result: {payload.summary[:100]}",
        source_ref=payload.source_ref or f"run://{run['run_id']}",
        repo_path=repo_path or None,
        task_id=payload.assignment_id,
        agent_id=str(metadata.get("agent_lane") or "manual"),
        tags=memory_tags,
    )
    _append_run_event(run["run_id"], "Manual result captured", f"Captured {result_kind} for lane {metadata.get('agent_lane', 'unknown')}.", "success", "evidence")
    return {
        "session_id": session_id,
        "run_id": run["run_id"],
        "artifacts": artifacts,
        "evidence_summary": payload.summary,
    }


@mcharness_router.post("/sessions/{session_id}/gate-decision")
def post_mcharness_gate_decision(session_id: str, payload: McHarnessGateDecisionRequest):
    thread = _thread_for_session(session_id)
    run = _run_for_session(session_id)
    gates = WORKBENCH_STORE.list_proof_gates(run["run_id"])
    gate = next((item for item in gates if item.status == "open"), gates[0] if gates else None)
    if gate is None:
        raise HTTPException(status_code=404, detail=f"No proof gate found for session: {session_id}")
    updated_run = WORKBENCH_STORE.decide_run_proof_gate(
        gate.gate_id,
        WorkbenchRunProofGateDecisionRequest(
            decision=payload.decision,
            actor="operator",
            note=payload.note,
        ),
    )
    artifact = _create_artifact(
        thread["thread_id"],
        "gate_decision",
        "Gate decision",
        "\n".join(
            [
                f"Gate id: {gate.gate_id}",
                f"Decision: {payload.decision}",
                f"Note: {payload.note or '(none)'}",
            ]
        ),
        payload.note or payload.decision,
        "md",
    )
    continuation = None
    if payload.continue_after:
        continuation = continue_captain_run(run["run_id"])
    run_summary = _create_run_summary_artifact(thread, updated_run, f"Gate {payload.decision} recorded.")
    return {
        "session_id": session_id,
        "run": updated_run,
        "gate_id": gate.gate_id,
        "decision": payload.decision,
        "artifact": artifact,
        "continuation": continuation,
        "run_summary_artifact": run_summary,
    }


@mcharness_router.get("/sessions/{session_id}/artifacts")
def get_mcharness_session_artifacts(session_id: str):
    _thread_for_session(session_id)
    artifacts = [
        artifact.model_dump(mode="json")
        for artifact in WORKBENCH_STORE.list_artifacts()
        if artifact.thread_id == session_id
    ]
    artifacts.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return {
        "session_id": session_id,
        "artifacts": artifacts,
    }


@mcharness_router.get("/sessions/{session_id}/git-status")
def get_mcharness_session_git_status(session_id: str):
    thread = _thread_for_session(session_id)
    return _capture_git_status_artifacts(thread)


@mcharness_router.get("/runs/recent")
def get_mcharness_runs_recent():
    if not _run_history_read_enabled():
        return {
            "service": "mcharness-control-plane",
            "service_mode": _service_mode_label(),
            "runs": [],
            "notes": ["Run history is available on the private runner service."],
        }
    runs = list_recent_runs(MCTABLE_ROOT)
    enriched = []
    for run in runs:
        row = dict(run)
        run_id = str(run.get("run_id") or "")
        if run_id:
            row["gate_status"] = gate_status_summary_for_run(MCTABLE_ROOT, run_id)
        enriched.append(row)
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "runs": enriched,
    }


@mcharness_router.get("/runs/{run_id}")
def get_mcharness_run_detail(run_id: str):
    if not _run_history_read_enabled():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    run = get_run_record(MCTABLE_ROOT, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    evidence = evidence_summaries_for_run(MCTABLE_ROOT, list(run.get("evidence_ids") or []))
    gates = list_gates_for_run(MCTABLE_ROOT, run_id)
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "run": {
            **run,
            "gate_status": (
                gate_summary := gate_status_summary_for_run(MCTABLE_ROOT, run_id)
            ),
            "gate_label": gate_ui_label(gate_summary),
        },
        "evidence": evidence,
        "gates": gates,
    }


@mcharness_router.get("/runs/{run_id}/report")
def get_mcharness_run_report(run_id: str):
    if not _run_history_read_enabled():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return build_run_report_payload(MCTABLE_ROOT, run_id)


@mcharness_router.post("/runs/{run_id}/evidence", dependencies=[Depends(_require_run_history_write)])
def post_mcharness_run_evidence(run_id: str, payload: McHarnessRunEvidenceCreateRequest):
    run = get_run_record(MCTABLE_ROOT, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    content = payload.content or payload.content_excerpt or payload.summary or ""
    if not content.strip():
        raise HTTPException(status_code=400, detail="Evidence content is required.")
    evidence = create_evidence_record(
        MCTABLE_ROOT,
        run_id=run_id,
        evidence_type=payload.type,
        title=payload.title,
        summary=payload.summary,
        content=content,
        content_excerpt=payload.content_excerpt,
        agent_id=payload.agent_id or run.get("agent_id"),
        source=payload.source,
    )
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "evidence": evidence,
    }


@mcharness_router.get("/evidence/recent")
def get_mcharness_evidence_recent(type: Optional[str] = None):
    if not _run_history_read_enabled():
        return {
            "service": "mcharness-control-plane",
            "service_mode": _service_mode_label(),
            "evidence": [],
            "notes": ["Evidence history is available on the private runner service."],
        }
    evidence = list_recent_evidence(MCTABLE_ROOT)
    if type:
        evidence = [item for item in evidence if str(item.get("type") or "") == type]
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "evidence": evidence,
        "filter_type": type,
    }


@mcharness_router.get("/gates/recent")
def get_mcharness_gates_recent():
    if not _run_history_read_enabled():
        return {
            "service": "mcharness-control-plane",
            "service_mode": _service_mode_label(),
            "gates": [],
            "notes": ["Proof gates are available on the private runner service."],
        }
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "gates": list_recent_gates(MCTABLE_ROOT),
    }


@mcharness_router.get("/runs/{run_id}/gates")
def get_mcharness_run_gates(run_id: str):
    if not _run_history_read_enabled():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    run = get_run_record(MCTABLE_ROOT, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "run_id": run_id,
        "gates": list_gates_for_run(MCTABLE_ROOT, run_id),
    }


@mcharness_router.post("/runs/{run_id}/gates", dependencies=[Depends(_require_run_history_write)])
def post_mcharness_run_gate(run_id: str, payload: McHarnessProofGateCreateRequest):
    run = get_run_record(MCTABLE_ROOT, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    gate = create_proof_gate(
        MCTABLE_ROOT,
        run_id=run_id,
        plan_id=payload.plan_id or run.get("plan_id"),
        step_id=payload.step_id,
        gate_type=payload.gate_type,
        title=payload.title,
        summary=payload.summary,
        evidence_ids=list(payload.evidence_ids or run.get("evidence_ids") or []),
    )
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "gate": gate,
    }


@mcharness_router.post("/runs/{run_id}/save-proof-memory")
def post_mcharness_run_save_proof_memory(run_id: str):
    """Write a proof or blocked_attempt memory for an existing run record.

    Useful when the run was created by a runner and the caller wants to
    ensure a Warden Memory entry exists for later recall.
    """
    run = get_run_record(MCTABLE_ROOT, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    plan_id = str(run.get("plan_id") or "")
    repo_id = str(run.get("repo_id") or "")
    status = str(run.get("status") or "")
    title = str(run.get("title") or run_id)
    kind = "blocked_attempt" if status == "blocked" else "proof"
    mem_id = _write_dispatch_memory(
        kind=kind,
        plan_id=plan_id,
        step_id="",
        step_title=title,
        run_id=run_id,
        repo_id=repo_id,
        lane_id=str(run.get("agent_id") or "codex_cli"),
        goal=title,
        reason=status,
        transcript_excerpt=str(run.get("transcript_excerpt") or ""),
    )
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "run_id": run_id,
        "memory_id": mem_id,
        "kind": kind,
    }


@mcharness_router.post("/gates/{gate_id}/decision", dependencies=[Depends(_require_run_history_write)])
def post_mcharness_gate_decision(gate_id: str, payload: McHarnessProofGateDecisionRequest):
    gate = get_proof_gate(MCTABLE_ROOT, gate_id)
    if gate is None:
        raise HTTPException(status_code=404, detail=f"Proof gate not found: {gate_id}")
    updated = decide_proof_gate(
        MCTABLE_ROOT,
        gate_id,
        decision=payload.decision,
        decided_by=payload.decided_by,
        decision_reason=payload.decision_reason,
    )
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "gate": updated,
    }


def _runner_session_inventory(*, include_details: bool = True) -> dict[str, Any]:
    return build_runner_session_inventory(
        MCTABLE_ROOT,
        safe_cmd=_safe_cmd,
        runner_state_root=RUNNER_STATE_ROOT,
        include_details=include_details and _codex_runner_ready(),
    )


def _mission_control_context() -> dict[str, Any]:
    captain_status = _captain_status_payload()
    return {
        "history_enabled": _run_history_read_enabled(),
        "codex_runner_ready": _codex_runner_ready(),
        "private_only": _agent_registry_private_only(),
        "captain_configured": bool(captain_status.get("configured")),
        "tmux_runner_enabled": _tmux_runner_enabled(),
        "codex_runner_enabled": _codex_runner_enabled(),
        "runner_inventory": _runner_session_inventory(include_details=_codex_runner_ready()),
    }


@mcharness_router.get("/mission-control/snapshot")
def get_mcharness_mission_control_snapshot():
    ctx = _mission_control_context()
    snapshot = build_mission_control_snapshot(MCTABLE_ROOT, **ctx)
    snapshot["service_mode"] = _service_mode_label()
    return snapshot


@mcharness_router.get("/runner/sessions")
def get_mcharness_runner_sessions():
    inventory = _runner_session_inventory(include_details=_codex_runner_ready())
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        **inventory,
    }


@mcharness_router.post("/runner/sessions/cleanup", dependencies=[Depends(_require_run_history_write)])
def post_mcharness_runner_sessions_cleanup(payload: McHarnessRunnerSessionCleanupRequest):
    result = cleanup_runner_sessions(
        MCTABLE_ROOT,
        safe_cmd=_safe_cmd,
        runner_state_root=RUNNER_STATE_ROOT,
        confirm=payload.confirm,
        stale_after_seconds=payload.stale_after_seconds,
    )
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        **result,
    }


@mcharness_router.get("/agents/health")
def get_mcharness_agents_health():
    ctx = _mission_control_context()
    from .mission_control import select_active_plan

    plan = select_active_plan(MCTABLE_ROOT, history_enabled=ctx["history_enabled"])
    items = build_agents_health_items(
        MCTABLE_ROOT,
        codex_runner_ready=ctx["codex_runner_ready"],
        private_only=ctx["private_only"],
        plan=plan,
        captain_configured=ctx["captain_configured"],
    )
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "items": items,
    }


@mcharness_router.get("/safety/status")
def get_mcharness_safety_status():
    ctx = _mission_control_context()
    payload = build_safety_payload(
        codex_runner_ready=ctx["codex_runner_ready"],
        tmux_runner_enabled=ctx["tmux_runner_enabled"],
        codex_runner_enabled=ctx["codex_runner_enabled"],
        jules_runnable=False,
        runner_inventory=ctx.get("runner_inventory"),
    )
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        **payload,
    }


@mcharness_router.post("/missions/{mission_id}/pause", dependencies=[Depends(_require_run_history_write)])
def post_mcharness_mission_pause(mission_id: str, payload: McHarnessMissionPauseRequest):
    updated = pause_mission(MCTABLE_ROOT, mission_id, note=payload.note)
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "mission_id": mission_id,
        "status": "stopped",
        "plan": _captain_plan_response(updated),
        "notes": ["Mission paused. No automatic runner cancellation was performed."],
    }


@mcharness_router.post("/missions/{mission_id}/adjust-plan", dependencies=[Depends(_require_run_history_write)])
def post_mcharness_mission_adjust_plan(mission_id: str, payload: McHarnessMissionAdjustPlanRequest):
    updated = adjust_mission_plan(
        MCTABLE_ROOT,
        mission_id,
        note=payload.note,
        adjustments=payload.adjustments or None,
    )
    return {
        "ok": True,
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "mission_id": mission_id,
        "human_review_required": True,
        "plan": _captain_plan_response(updated),
        "notes": ["Plan adjustment recorded. Human review is required before changes are applied."],
    }


@mcharness_router.get("/worklog/recent")
def get_mcharness_worklog_recent():
    if not _run_history_read_enabled():
        return {
            "service": "mcharness-control-plane",
            "service_mode": _service_mode_label(),
            "items": [],
            "notes": ["Mission worklog is available on the private runner service."],
        }
    items = list_recent_worklog(MCTABLE_ROOT)
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "items": [
            {
                **item,
                "label": EVENT_LABELS.get(str(item.get("kind")), str(item.get("kind") or "event")),
            }
            for item in items
        ],
    }


@mcharness_router.get("/evidence/{evidence_id}")
def get_mcharness_evidence_detail(evidence_id: str):
    if not _run_history_read_enabled():
        raise HTTPException(status_code=404, detail=f"Evidence not found: {evidence_id}")
    evidence = get_evidence_record(MCTABLE_ROOT, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail=f"Evidence not found: {evidence_id}")
    linked_run = None
    run_id = evidence.get("run_id")
    if run_id:
        linked_run = get_run_record(MCTABLE_ROOT, str(run_id))
        if linked_run:
            linked_run = {
                "run_id": linked_run.get("run_id"),
                "title": linked_run.get("title"),
                "status": linked_run.get("status"),
            }
    return {
        "service": "mcharness-control-plane",
        "service_mode": _service_mode_label(),
        "evidence": evidence,
        "linked_run": linked_run,
    }


@legacy_router.post("/api/mctable/local/dispatch-launch")
def disabled_legacy_launch_route():
    raise HTTPException(status_code=400, detail="deprecated/disabled legacy launch route")


# ---------------------------------------------------------------------------
# Command Deck endpoints
# ---------------------------------------------------------------------------

import os as _os

_BOARD_ROOT = Path(_os.getenv("WARDEN_BOARD_ROOT", _os.getenv("MCTABLE_BOARD_ROOT", "~/.local/share/warden/board"))).expanduser()
_BOARD_TASK_STATUSES = ["queued", "claimed", "running", "needs_review", "failed", "completed", "done"]


def _cd_load_tasks(status: str, limit: int = 20):
    d = _BOARD_ROOT / "tasks" / status
    if not d.exists():
        return []
    tasks = []
    for f in sorted(d.glob("*.json"), reverse=True)[:limit]:
        try:
            tasks.append(json.loads(f.read_text()))
        except Exception:
            pass
    return tasks


def _cd_load_proofs(limit: int = 20):
    """Load recent proof/failure/handoff memories."""
    try:
        from .workbench import WorkbenchStore
        store = WorkbenchStore()
        mems = store.search_memories("", limit=limit)
        return [
            m.model_dump(mode="json")
            for m in mems
            if m.kind in ("proof", "failure", "handoff", "decision")
        ]
    except Exception:
        return []


def _cd_load_relay(limit: int = 30):
    """Load recent dispatch/activity events."""
    events = []
    act_root = _BOARD_ROOT / "activity"
    if not act_root.exists():
        return []
    for day_dir in sorted(act_root.iterdir(), reverse=True)[:3]:
        for f in sorted(day_dir.glob("*.jsonl"), reverse=True):
            try:
                for line in f.read_text().splitlines():
                    if line.strip():
                        events.append(json.loads(line))
                        if len(events) >= limit:
                            return events
            except Exception:
                pass
    return events


@mcharness_router.get("/warden/command-deck/state")
def get_command_deck_state():
    all_tasks = []
    for status in _BOARD_TASK_STATUSES:
        for t in _cd_load_tasks(status):
            t.setdefault("status", status)
            all_tasks.append(t)

    # Proof gate: flag verified tasks without closeout
    for t in all_tasks:
        if t.get("status") in ("completed", "done"):
            if not t.get("proof_id") and not t.get("proof") and not t.get("failure"):
                t["proof_gate"] = "proof_needed"
            else:
                t["proof_gate"] = "verified"
        else:
            t["proof_gate"] = "not_required"

    return {
        "ok": True,
        "tasks": all_tasks,
        "summary": {
            "queued": sum(1 for t in all_tasks if t.get("status") == "queued"),
            "running": sum(1 for t in all_tasks if t.get("status") in ("running", "claimed")),
            "needs_review": sum(1 for t in all_tasks if t.get("status") == "needs_review"),
            "proof_needed": sum(1 for t in all_tasks if t.get("proof_gate") == "proof_needed"),
            "failed": sum(1 for t in all_tasks if t.get("status") == "failed"),
        },
    }


@mcharness_router.get("/warden/command-deck/proofs")
def get_command_deck_proofs():
    return {"ok": True, "proofs": _cd_load_proofs(limit=30)}


@mcharness_router.get("/warden/command-deck/relay")
def get_command_deck_relay():
    return {"ok": True, "events": _cd_load_relay(limit=50)}


@mcharness_router.get("/warden/command-deck/events")
def get_command_deck_events():
    """SSE-compatible endpoint — returns latest events as JSON for polling."""
    return {
        "ok": True,
        "events": _cd_load_relay(limit=20),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class _DemoSeedRequest(BaseModel):
    title: str = "Demo Mission"
    description: str = "Demonstrate Warden Command Deck dispatch loop."
    agent: str = "cl"
    priority: str = "medium"


@mcharness_router.post("/warden/command-deck/demo-seed", status_code=201)
def post_command_deck_demo_seed(req: Optional[_DemoSeedRequest] = None):
    if req is None:
        req = _DemoSeedRequest()
    import uuid as _uuid
    from .workspace_authority import get_canonical_repo
    task_id = f"demo-{_uuid.uuid4().hex[:8]}"
    task = {
        "task_id": task_id,
        "title": req.title,
        "description": req.description,
        "agent": req.agent,
        "priority": req.priority,
        "project_id": "warden",
        "repo_path": get_canonical_repo("warden") or "",
        "workspace_checked": False,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tags": ["demo"],
    }
    dest = _BOARD_ROOT / "tasks" / "queued"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{task_id}.json").write_text(json.dumps(task, indent=2))
    return {"ok": True, "task": task}


# -- Dispatch controls --

class _TaskCreateRequest(BaseModel):
    title: str
    description: str = ""
    agent: str = "any"
    priority: str = "medium"
    project: str = ""
    project_id: str = "warden"
    branch: str = ""
    repo_path: str = ""  # defaults to canonical Warden repo if empty
    workspace_checked: bool = False


@mcharness_router.post("/warden/command-deck/tasks", status_code=201)
def post_command_deck_task(req: _TaskCreateRequest):
    import uuid as _uuid
    from .workspace_authority import get_canonical_repo
    task_id = f"wt-{_uuid.uuid4().hex[:8]}"
    # Default repo_path to canonical for the project
    repo_path = req.repo_path or get_canonical_repo(req.project_id) or ""
    task = {
        "task_id": task_id,
        "title": req.title,
        "description": req.description,
        "agent": req.agent,
        "priority": req.priority,
        "project": req.project or req.project_id,
        "project_id": req.project_id,
        "branch": req.branch,
        "repo_path": repo_path,
        "workspace_checked": req.workspace_checked,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    dest = _BOARD_ROOT / "tasks" / "queued"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{task_id}.json").write_text(json.dumps(task, indent=2))
    return {"ok": True, "task": task}


def _cd_find_task(task_id: str):
    for status in _BOARD_TASK_STATUSES:
        f = _BOARD_ROOT / "tasks" / status / f"{task_id}.json"
        if f.exists():
            try:
                return json.loads(f.read_text()), f
            except Exception:
                pass
    return None, None


def _cd_move_task(task_id: str, dest_status: str) -> dict:
    task, src = _cd_find_task(task_id)
    if not task or not src:
        raise HTTPException(404, f"Task not found: {task_id}")
    dest_dir = _BOARD_ROOT / "tasks" / dest_status
    dest_dir.mkdir(parents=True, exist_ok=True)
    task["status"] = dest_status
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    (dest_dir / src.name).write_text(json.dumps(task, indent=2))
    src.unlink(missing_ok=True)
    return task


@mcharness_router.post("/warden/command-deck/tasks/{task_id}/claim")
def post_cd_task_claim(task_id: str):
    task = _cd_move_task(task_id, "claimed")
    return {"ok": True, "task": task}


class _ProofBody(BaseModel):
    summary: str = ""
    files_changed: list = []
    commands_run: list = []


@mcharness_router.post("/warden/command-deck/tasks/{task_id}/proof")
def post_cd_task_proof(task_id: str, body: _ProofBody):
    task, src = _cd_find_task(task_id)
    if not task or not src:
        raise HTTPException(404, f"Task not found: {task_id}")
    task["proof"] = {
        "summary": body.summary,
        "files_changed": body.files_changed,
        "commands_run": body.commands_run,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    task["proof_gate"] = "verified"
    task["status"] = "completed"
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    dest = _BOARD_ROOT / "tasks" / "completed"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / src.name).write_text(json.dumps(task, indent=2))
    src.unlink(missing_ok=True)
    return {"ok": True, "task": task}


class _FailureBody(BaseModel):
    reason: str = ""
    blocker: str = ""


@mcharness_router.post("/warden/command-deck/tasks/{task_id}/failure")
def post_cd_task_failure(task_id: str, body: _FailureBody):
    task, src = _cd_find_task(task_id)
    if not task or not src:
        raise HTTPException(404, f"Task not found: {task_id}")
    task["failure"] = {
        "reason": body.reason,
        "blocker": body.blocker,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    task["proof_gate"] = "failed"
    task["status"] = "failed"
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    dest = _BOARD_ROOT / "tasks" / "failed"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / src.name).write_text(json.dumps(task, indent=2))
    src.unlink(missing_ok=True)
    return {"ok": True, "task": task}


class _HandoffBody(BaseModel):
    to_agent: str
    note: str = ""
    next_action: str = ""


@mcharness_router.post("/warden/command-deck/tasks/{task_id}/handoff")
def post_cd_task_handoff(task_id: str, body: _HandoffBody):
    task, src = _cd_find_task(task_id)
    if not task or not src:
        raise HTTPException(404, f"Task not found: {task_id}")
    task["handoff"] = {
        "to_agent": body.to_agent,
        "note": body.note,
        "next_action": body.next_action,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    task["agent"] = body.to_agent
    task["status"] = "queued"
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    dest = _BOARD_ROOT / "tasks" / "queued"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / src.name).write_text(json.dumps(task, indent=2))
    src.unlink(missing_ok=True)
    return {"ok": True, "task": task}


@mcharness_router.post("/warden/command-deck/tasks/{task_id}/dispatch")
def post_cd_task_dispatch(task_id: str):
    from .agent_dispatcher import AgentDispatcher
    task, src = _cd_find_task(task_id)
    if not task or not src:
        raise HTTPException(404, f"Task not found: {task_id}")
    dispatcher = AgentDispatcher(dry_run=True)
    result = dispatcher.dispatch_task(task, src)
    return {
        "ok": result.success,
        "task_id": result.task_id,
        "run_id": result.run_id,
        "summary": result.summary,
        "log": str(result.log_path) if result.log_path else None,
        "dry_run": True,
    }


# ---------------------------------------------------------------------------
# Daily Brief endpoint
# ---------------------------------------------------------------------------

@mcharness_router.post("/warden/notion/daily-brief")
def post_warden_daily_brief():
    """Generate today's Warden daily brief and save locally."""
    from .daily_brief import generate_and_save
    result = generate_and_save()
    return result


@mcharness_router.get("/warden/notion/daily-brief")
def get_warden_daily_brief():
    """Return today's brief markdown (generate if not yet created)."""
    from .daily_brief import generate_and_save
    result = generate_and_save()
    return result


# ---------------------------------------------------------------------------
# Notion sync dry-run endpoints
# ---------------------------------------------------------------------------

class _NotionSyncRequest(BaseModel):
    existing_candidates: list = []


@mcharness_router.get("/warden/notion/sync/status")
def get_warden_notion_sync_status():
    """Return redacted Notion sync readiness; never exposes secret values."""
    from .notion_sync import notion_sync_status
    return notion_sync_status()


@mcharness_router.post("/warden/notion/sync/dry-run")
def post_warden_notion_sync_dry_run(req: Optional[_NotionSyncRequest] = None):
    """Preview Warden board tasks that would become Notion inbox candidates."""
    from .notion_sync import sync_candidates_dry_run
    existing = req.existing_candidates if req else []
    return sync_candidates_dry_run(_BOARD_ROOT, existing_candidates=existing)


@mcharness_router.post("/warden/notion/sync/write")
def post_warden_notion_sync_write(req: Optional[_NotionSyncRequest] = None):
    """Blocked v0 write path; real Notion writes are intentionally disabled."""
    from .notion_sync import sync_candidates_write
    existing = req.existing_candidates if req else []
    return sync_candidates_write(_BOARD_ROOT, existing_candidates=existing)


# ---------------------------------------------------------------------------
# Workspace Authority endpoints
# ---------------------------------------------------------------------------

@mcharness_router.get("/warden/workspaces")
def get_workspaces():
    from .workspace_authority import list_projects
    return {"ok": True, "projects": list_projects()}


@mcharness_router.get("/warden/workspaces/{project_id}")
def get_workspace(project_id: str):
    from .workspace_authority import resolve_project
    p = resolve_project(project_id)
    if not p:
        raise HTTPException(404, f"Unknown project: {project_id!r}")
    return {"ok": True, "project": p}


class _ResolveRequest(BaseModel):
    project_id: str
    cwd: Optional[str] = None


@mcharness_router.post("/warden/workspaces/resolve")
def post_workspace_resolve(req: _ResolveRequest):
    from .workspace_authority import detect_workspace_drift
    import os as _os2
    result = detect_workspace_drift(req.project_id, req.cwd or _os2.getcwd())
    return {"ok": result.get("safe_to_edit", False), **result}


class _BootstrapRequest(BaseModel):
    project_id: str
    task: str = ""
    cwd: Optional[str] = None


@mcharness_router.post("/warden/workspaces/bootstrap")
def post_workspace_bootstrap(req: _BootstrapRequest):
    from .workspace_authority import build_agent_bootstrap
    return build_agent_bootstrap(req.project_id, task=req.task, cwd=req.cwd)


# ---------------------------------------------------------------------------
# Memory Watcher endpoints
# ---------------------------------------------------------------------------

@mcharness_router.get("/warden/memory-watcher/status")
def get_memory_watcher_status():
    from .memory_watcher import get_watcher_status
    return {"ok": True, **get_watcher_status()}


@mcharness_router.post("/warden/memory-watcher/start")
def post_memory_watcher_start():
    from .memory_watcher import start_background_watcher
    result = start_background_watcher(dry_run=False)
    return {"ok": True, "result": result}


@mcharness_router.post("/warden/memory-watcher/stop")
def post_memory_watcher_stop():
    from .memory_watcher import stop_background_watcher
    result = stop_background_watcher()
    return {"ok": True, "result": result}


@mcharness_router.post("/warden/memory-watcher/collect")
def post_memory_watcher_collect():
    """Trigger one immediate collection pass (for testing / manual trigger)."""
    from .memory_watcher import MemoryWatcher
    w = MemoryWatcher(dry_run=False)
    n = w.poll_once()
    return {"ok": True, "memories_written": n}


@mcharness_router.post("/warden/memory-watcher/install-hooks")
def post_memory_watcher_install_hooks():
    from .memory_watcher import install_git_hooks, CANONICAL_REPO
    installed = install_git_hooks(CANONICAL_REPO)
    return {"ok": True, "installed": installed}


@mcharness_router.post("/warden/memory-watcher/uninstall-hooks")
def post_memory_watcher_uninstall_hooks():
    from .memory_watcher import uninstall_git_hooks, CANONICAL_REPO
    removed = uninstall_git_hooks(CANONICAL_REPO)
    return {"ok": True, "removed": removed}


# ---------------------------------------------------------------------------
# Memory Chat Agent
# ---------------------------------------------------------------------------

class _MemoryChatMessage(BaseModel):
    role: str = "user"
    content: str


class _MemoryChatRequest(BaseModel):
    message: str
    history: list[_MemoryChatMessage] = []
    model: Optional[str] = None


class _AgentChatRequest(BaseModel):
    message: str
    history: list[_MemoryChatMessage] = []


@mcharness_router.post("/warden/agent/chat")
async def post_warden_agent_chat(req: _AgentChatRequest):
    """WardenAgent — tool-calling agent for 'where we at?' queries.

    Pulls from memory, git, GitHub PRs/issues, and web search.
    Uses cloud LLM (Groq/Cerebras/OpenRouter) with Ollama fallback.
    """
    from .agent import run_agent
    history = [{"role": m.role, "content": m.content} for m in req.history]
    result = await run_agent(message=req.message, history=history)
    return {
        "ok": True,
        "reply": result.reply,
        "tools_used": result.tools_used,
        "sources": result.sources,
        "model": result.model,
        "provider": result.provider,
        "fallback": result.fallback,
        "trace": result.trace,
    }


@mcharness_router.post("/warden/memory-agent/chat")
async def post_memory_agent_chat(req: _MemoryChatRequest):
    """Chat with the Warden Memory Agent — synthesizes git, shell, browser, tasks, and stored memories."""
    from .memory_agent import chat as agent_chat
    history = [{"role": m.role, "content": m.content} for m in req.history]
    result = agent_chat(message=req.message, history=history, model=req.model)
    return {
        "ok": True,
        "reply": result.reply,
        "sources": result.sources,
        "model_used": result.model_used,
        "context_snapshot": result.context_snapshot,
        "fallback": result.fallback,
        "trace": result.trace,
    }


@mcharness_router.get("/warden/memory-agent/context")
def get_memory_agent_context():
    """Return a snapshot of current context without LLM — for UI pre-loading."""
    from .memory_agent import gather_context
    ctx = gather_context()
    return {
        "ok": True,
        "branch": ctx.current_branch,
        "recent_commits": ctx.git_log[:8],
        "shell_commands": ctx.shell_commands[-10:],
        "browser_visits": ctx.browser_visits[-8:],
        "board_tasks": [
            {"status": t.get("status"), "title": t.get("title"), "agent": t.get("agent")}
            for t in ctx.board_tasks[:6]
        ],
        "memory_count": len(ctx.recent_memories),
        "gathered_at": ctx.gathered_at,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Model Gateway Control Room endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class _RoutePreviewRequest(BaseModel):
    task: str
    force_alias: Optional[str] = None

class _ContextPreviewRequest(BaseModel):
    query: str
    alias: Optional[str] = None
    memories: list[dict] = []
    git_context: Optional[str] = None
    tool_outputs: list[dict] = []
    system_prompt: Optional[str] = None


@mcharness_router.get("/warden/model-gateway/status")
def get_gateway_status():
    """Provider reachability and key status. Never exposes raw key values."""
    from .gateway.providers import check_all
    return {"ok": True, "providers": check_all()}


@mcharness_router.get("/warden/model-gateway/aliases")
def get_gateway_aliases():
    """All 6 model aliases with metadata."""
    from .gateway.aliases import ALIAS_DEFS
    return {"ok": True, "aliases": ALIAS_DEFS}


@mcharness_router.post("/warden/model-gateway/route-preview")
def post_route_preview(req: _RoutePreviewRequest):
    """Preview how a task would be routed — no cloud token spend."""
    from .gateway.policy import route
    from .gateway.context_budget import _count_tokens, _ALIAS_BUDGETS
    d = route(req.task, force_alias=req.force_alias)
    input_tokens = d.estimated_input_tokens
    budget = _ALIAS_BUDGETS.get(d.alias, 4096)
    tokens_after = min(input_tokens, budget)
    pct_saved = round((input_tokens - tokens_after) / max(1, input_tokens) * 100, 1) if input_tokens > budget else 0.0
    from .gateway.aliases import ALIAS_DEFS
    alias_def = ALIAS_DEFS.get(d.alias, {})
    return {
        "ok": True,
        "alias": d.alias,
        "reason": d.reason,
        "confidence": round(d.confidence, 2),
        "classifier_used": d.classifier_used,
        "privacy": d.privacy,
        "openrouter_free_blocked": d.openrouter_free_blocked,
        "estimated_input_tokens": input_tokens,
        "token_budget": budget,
        "estimated_tokens_after_budget": tokens_after,
        "pct_saved": pct_saved,
        "likely_tools": d.likely_tools,
        "primary_provider": alias_def.get("primary_provider"),
        "fallback_provider": alias_def.get("fallback_provider"),
        "warnings": d.warnings,
    }


@mcharness_router.post("/warden/model-gateway/context-preview")
def post_context_preview(req: _ContextPreviewRequest):
    """Show exactly what context would be kept/dropped/compressed for a given alias."""
    from .gateway.policy import route
    from .gateway.context_budget import build_budget, inspect
    alias = req.alias or route(req.query).alias
    result = build_budget(
        alias=alias,
        query=req.query,
        memories=req.memories or [],
        git_context=req.git_context,
        tool_outputs=req.tool_outputs or [],
        system_prompt=req.system_prompt,
    )
    return {
        "ok": True,
        "alias": alias,
        "token_budget": result.token_budget,
        "tokens_before": result.total_before,
        "tokens_after": result.total_after,
        "tokens_saved": result.tokens_saved,
        "pct_saved": result.pct_saved,
        "items": inspect(result),
    }


@mcharness_router.get("/warden/model-gateway/traces")
def get_gateway_traces(limit: int = 50):
    """Recent gateway request traces — task, alias, provider, token savings."""
    from .gateway.traces import recent
    return {"ok": True, "traces": recent(limit=min(limit, 200))}


# ── Browser extension ingest ──────────────────────────────────────────────────

class BrowserIngestRequest(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)


@mcharness_router.post("/warden/browser/ingest", status_code=201)
def browser_ingest(req: BrowserIngestRequest):
    """Receive batched browser events from the Warden Chrome extension.

    Each event has: source, kind, url, title, ts — plus kind-specific fields
    (query, text, messages, fields, etc.). Stored as WorkbenchMemory entries
    grouped by kind so they're searchable via Memory Agent.
    """
    from .workbench import WorkbenchStore, WorkbenchMemoryCreateRequest
    import hashlib

    if not req.events:
        return {"ok": True, "stored": 0}

    store = WorkbenchStore()
    stored = 0
    skipped = 0

    # Group events by kind for richer memory summaries
    kind_groups: dict[str, list[dict]] = {}
    for ev in req.events[:500]:  # cap per batch
        k = ev.get("kind", "browse")
        kind_groups.setdefault(k, []).append(ev)

    for kind, events in kind_groups.items():
        for ev in events:
            url = (ev.get("url") or "")[:300]
            title = (ev.get("title") or "")[:200]
            ts = ev.get("ts") or ""
            source = ev.get("source") or "browser"

            # Build a summary line per event kind
            if kind == "search":
                query = (ev.get("query") or "").strip()
                if not query:
                    skipped += 1
                    continue
                engine = ev.get("engine", "google")
                summary = f"[{engine} search] {query}"
                content = f"Searched {engine}: {query}\nURL: {url}"

            elif kind == "ai_conversation":
                messages = ev.get("messages") or []
                if not messages:
                    skipped += 1
                    continue
                service = ev.get("source", "ai").replace("_turn", "")
                turns = "\n".join(
                    f"{m.get('role','?').upper()}: {m.get('text','')[:400]}"
                    for m in messages[:6]
                )
                summary = f"[{service}] conversation — {len(messages)} turn(s)"
                content = f"Service: {service}\nURL: {url}\n\n{turns}"

            elif kind == "selection":
                text = (ev.get("selected_text") or "").strip()
                if not text:
                    skipped += 1
                    continue
                summary = f"[selected] {text[:120]}"
                content = f"Selected on {title or url}:\n{text}\nURL: {url}"

            elif kind == "input":
                text = (ev.get("text") or "").strip()
                fields = ev.get("fields") or {}
                body = text or "; ".join(f"{k}={v}" for k, v in fields.items())
                if not body:
                    skipped += 1
                    continue
                summary = f"[typed] {body[:120]}"
                content = f"Typed on {title or url}:\n{body}\nURL: {url}"

            elif kind == "copy":
                text = (ev.get("text") or "").strip()
                if not text:
                    skipped += 1
                    continue
                summary = f"[copied] {text[:120]}"
                content = f"Copied from {title or url}:\n{text}\nURL: {url}"

            elif kind == "github":
                pr = ev.get("pr")
                issue = ev.get("issue")
                repo = f"{ev.get('owner','')}/{ev.get('repo','')}"
                detail = f"PR #{pr}" if pr else (f"issue #{issue}" if issue else ev.get("path", ""))
                summary = f"[github] {repo} {detail}".strip()
                content = f"GitHub: {repo} {detail}\nURL: {url}"

            elif kind == "media":
                yt_title = ev.get("title") or title
                channel = ev.get("channel") or ""
                summary = f"[youtube] {yt_title}" + (f" — {channel}" if channel else "")
                content = f"Watched: {yt_title}\nChannel: {channel}\nURL: {url}"

            elif kind == "reference":
                h1 = ev.get("title") or title
                snippet = (ev.get("snippet") or "").strip()
                summary = f"[docs] {h1[:120]}"
                content = f"Docs: {h1}\nURL: {url}" + (f"\n\n{snippet}" if snippet else "")

            elif kind == "browse":
                if not title and not url:
                    skipped += 1
                    continue
                dwell = ev.get("dwell_sec", 0)
                if dwell < 5 and source != "navigation":
                    skipped += 1
                    continue
                scroll = ev.get("scroll_pct", 0)
                summary = f"[browsed] {title or url[:80]}"
                content = f"Visited: {title or url}\nURL: {url}\nDwell: {dwell}s, scroll: {scroll}%"

            else:
                summary = f"[{kind}] {title or url[:80]}"
                content = f"Kind: {kind}\nURL: {url}\nTitle: {title}"

            # Dedup by content hash
            dedup = hashlib.sha1(f"{summary}|{url}".encode()).hexdigest()[:12]
            memory_id = f"browser-{dedup}"

            try:
                existing = store.search_memories(memory_id, limit=1)
                if any(m.memory_id == memory_id for m in existing):
                    skipped += 1
                    continue
                store.create_memory(WorkbenchMemoryCreateRequest(
                    memory_id=memory_id,
                    scope="warden",
                    summary=summary,
                    source="browser_extension",
                    title=summary[:80],
                    kind="user_note",
                    tags=["auto", "browser", kind],
                    metadata={
                        "url": url,
                        "title": title,
                        "ts": ts,
                        "source": source,
                        "raw": {k: v for k, v in ev.items() if k not in ("url", "title", "ts", "source")
                                and not isinstance(v, (dict, list))},
                    },
                ))
                stored += 1
            except Exception:
                skipped += 1

    return {"ok": True, "stored": stored, "skipped": skipped, "received": len(req.events)}


# ---------------------------------------------------------------------------
# Warden Connectors — account connection platform
# ---------------------------------------------------------------------------

@mcharness_router.get("/warden/connectors/providers")
def get_warden_connectors_providers():
    """List available connector providers with configuration status."""
    from .connectors.registry import list_providers
    from .connectors.oauth import is_provider_configured
    providers = list_providers()
    # Override configured flag to reflect vault-stored configs too
    for p in providers:
        if p.get("provider_id") == "gmail":
            # Gmail primary path is IMAP app-password — no pre-config needed
            p["configured"] = True
        elif p.get("auth_type") == "oauth2_authorization_code":
            p["configured"] = is_provider_configured(p["provider_id"])
    return {"ok": True, "providers": providers}


@mcharness_router.get("/warden/connectors/accounts")
def get_warden_connectors_accounts():
    """List connected user accounts. Tokens are never returned."""
    from .connectors.store import list_accounts
    return {"ok": True, "accounts": list_accounts(redact=True)}


@mcharness_router.post("/warden/connectors/{provider}/connect/start")
def post_warden_connectors_connect_start(provider: str, request: Request):
    """Begin an OAuth2 connection flow for the given provider."""
    from .connectors.oauth import start_oauth_flow
    base_url = str(request.base_url).rstrip("/")
    result = start_oauth_flow(provider, base_url)
    if result.get("configured") is False:
        return {"ok": False, "configured": False, "provider": provider,
                "error": result.get("error", "Provider not configured")}
    return {"ok": True, "provider": provider, "auth_url": result.get("auth_url"),
            "state": result.get("state")}


@mcharness_router.get("/warden/connectors/{provider}/callback")
def get_warden_connectors_callback(provider: str, code: str = "", state: str = "", error: str = ""):
    """OAuth2 callback — validates state, exchanges code for token, stores account."""
    from .connectors.oauth import validate_callback_state, exchange_code_for_token, _extract_email_from_token
    from .connectors.store import ConnectorStore
    from .connectors.models import ConnectedAccount
    import uuid as _uuid
    from datetime import datetime, timezone as _tz

    if error:
        return {"ok": False, "error": error, "provider": provider,
                "message": f"OAuth denied: {error}"}
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")
    state_data = validate_callback_state(state)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    redirect_uri = state_data.get("redirect_uri", "")
    token_response = exchange_code_for_token(provider, code, redirect_uri)

    if "error" in token_response:
        return {"ok": False, "provider": provider, "status": "token_exchange_failed",
                "error": token_response.get("error"),
                "message": token_response.get("error_description", "Token exchange failed")}

    # Store token securely, record account
    email = _extract_email_from_token(token_response, provider)
    account_id = f"{provider}-{_uuid.uuid4().hex[:12]}"
    now = datetime.now(_tz.utc).isoformat()
    scopes = state_data.get("scopes", [])

    # Serialize token as JSON string for vault storage
    import json as _json
    token_str = _json.dumps({
        "access_token": token_response.get("access_token", ""),
        "refresh_token": token_response.get("refresh_token", ""),
        "expires_in": token_response.get("expires_in"),
        "token_type": token_response.get("token_type", "Bearer"),
    })

    account = ConnectedAccount(
        account_id=account_id,
        user_id="local",
        provider=provider,
        display_email=email or f"{provider}_user",
        status="connected",
        scopes=scopes,
        capabilities=["mail.read", "mail.search"],
        created_at=now,
        updated_at=now,
        token_ref="",
    )
    store = ConnectorStore()
    stored = store.save_account(account, token=token_str)

    # Return success page (user may be in a popup window)
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Warden — Connected</title>
<style>body{{font-family:sans-serif;background:#0d1b2e;color:#d4e4f5;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
.card{{background:#14243c;border:1px solid rgba(100,160,255,.25);border-radius:10px;padding:32px 40px;text-align:center;max-width:360px;}}
h2{{margin:0 0 8px;}}p{{color:#8faabf;margin:0 0 16px;}}
.btn{{background:#2d5f9e;color:#d4e4f5;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:.9rem;}}
.btn:hover{{background:#3a72b8;}}</style>
</head>
<body><div class="card">
<h2>&#10003; {provider.title()} Connected</h2>
<p>{email or "Account connected successfully."}</p>
<button class="btn" id="doneBtn">Done</button>
</div>
<script>
(function(){{
  var origin = location.origin;
  if(window.opener){{
    try{{window.opener.postMessage({{type:"warden_connector_connected",provider:{json.dumps(provider)}}},origin);}}catch(e){{}}
  }}
  document.getElementById("doneBtn").onclick = function(){{ window.close(); }};
}})();
</script>
</body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_body)


@mcharness_router.post("/warden/connectors/accounts/{account_id}/disconnect")
def post_warden_connectors_disconnect(account_id: str):
    """Disconnect a connected account and remove its stored token."""
    from .connectors.store import ConnectorStore
    store = ConnectorStore()
    removed = store.disconnect_account(account_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")
    return {"ok": True, "account_id": account_id, "status": "disconnected"}


# ─── Provider OAuth config (stored in vault, not env vars) ───────────────────

class ProviderConfigRequest(BaseModel):
    client_id: str
    client_secret: str


@mcharness_router.get("/warden/connectors/{provider}/config")
def get_provider_oauth_config(provider: str):
    """Return masked provider OAuth config. Never returns the raw client_secret."""
    from .connectors.oauth import load_provider_config, is_provider_configured, _PROVIDER_CONFIG_SUPPORTED
    if provider not in _PROVIDER_CONFIG_SUPPORTED:
        raise HTTPException(status_code=404, detail=f"Provider {provider} does not support OAuth config")
    cfg = load_provider_config(provider)
    client_id = cfg.get("client_id", "")
    has_secret = bool(cfg.get("client_secret", ""))
    return {
        "ok": True,
        "provider": provider,
        "configured": bool(client_id),
        "client_id": client_id,
        "has_secret": has_secret,
        "source": "vault" if client_id else "none",
    }


@mcharness_router.post("/warden/connectors/{provider}/config")
def post_provider_oauth_config(provider: str, body: ProviderConfigRequest):
    """Save provider OAuth client credentials to the local vault."""
    from .connectors.oauth import save_provider_config, _PROVIDER_CONFIG_SUPPORTED
    if provider not in _PROVIDER_CONFIG_SUPPORTED:
        raise HTTPException(status_code=404, detail=f"Provider {provider} does not support OAuth config")
    client_id = (body.client_id or "").strip()
    client_secret = (body.client_secret or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    if not client_secret:
        raise HTTPException(status_code=400, detail="client_secret is required")
    save_provider_config(provider, client_id, client_secret)
    masked = client_id[:6] + "..." if len(client_id) > 6 else client_id
    return {"ok": True, "provider": provider, "configured": True,
            "client_id_preview": masked, "has_secret": True}


@mcharness_router.delete("/warden/connectors/{provider}/config")
def delete_provider_oauth_config(provider: str):
    """Remove stored provider OAuth config from vault."""
    from .connectors.oauth import clear_provider_config, _PROVIDER_CONFIG_SUPPORTED
    if provider not in _PROVIDER_CONFIG_SUPPORTED:
        raise HTTPException(status_code=404, detail=f"Provider {provider} does not support OAuth config")
    clear_provider_config(provider)
    return {"ok": True, "provider": provider, "configured": False}


# ─── Gmail app-password connect (IMAP, primary path) ─────────────────────────

class GmailImapConnectRequest(BaseModel):
    email: str
    app_password: str


@mcharness_router.post("/warden/connectors/gmail/connect/app-password")
def post_warden_gmail_imap_connect(body: GmailImapConnectRequest):
    """Connect Gmail via Google App Password (IMAP). No OAuth required.

    App password stored in local vault only — never returned to caller.
    Requires IMAP enabled in Gmail settings and 2-Step Verification active.
    """
    from .connectors.store import ConnectorStore
    from .connectors.models import ConnectedAccount
    import re as _re
    import uuid as _uuid
    from datetime import datetime, timezone as _tz
    import json as _json

    email = (body.email or "").strip().lower()
    app_password = (body.app_password or "").strip().replace(" ", "")

    if not email or not _re.match(r"[^@]+@[^@]+\.[^@]+", email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if not app_password:
        raise HTTPException(status_code=400, detail="app_password is required")
    if len(app_password) < 8:
        raise HTTPException(status_code=400, detail="App password too short (Google App Passwords are 16 characters)")

    # Optional live IMAP connection check
    connection_status = "connected"
    connection_note = ""
    try:
        from .mail.gmail_imap import GmailImapProvider
        probe = GmailImapProvider(email_addr=email, app_password=app_password, account_id="probe")
        if not probe.check_connection():
            connection_status = "needs_check"
            connection_note = (
                "Gmail IMAP login could not be verified. "
                "Confirm IMAP is enabled (Gmail → Settings → Forwarding and POP/IMAP) "
                "and that this is a Google App Password, not your normal password."
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        # Network unavailable or timeout — store anyway
        connection_status = "needs_check"
        connection_note = "Could not reach Gmail to verify. Credentials stored; test mail search to confirm."

    account_id = f"gmail-{_uuid.uuid4().hex[:12]}"
    now = datetime.now(_tz.utc).isoformat()
    token_str = _json.dumps({"email": email, "app_password": app_password, "auth_type": "imap_app_password"})

    account = ConnectedAccount(
        account_id=account_id,
        user_id="local",
        provider="gmail",
        display_email=email,
        status=connection_status,
        scopes=[],
        capabilities=["mail.read", "mail.search"],
        created_at=now,
        updated_at=now,
    )
    store = ConnectorStore()
    store.save_account(account, token=token_str)
    response = {
        "ok": True,
        "account_id": account_id,
        "provider": "gmail",
        "auth_type": "imap_app_password",
        "display_email": email,
        "status": connection_status,
    }
    if connection_note:
        response["note"] = connection_note
    return response


# ─── iCloud app-password connect ─────────────────────────────────────────────

class ICloudConnectRequest(BaseModel):
    email: str
    app_password: str


@mcharness_router.post("/warden/connectors/icloud/connect/app-password")
def post_warden_icloud_connect(body: ICloudConnectRequest):
    """Connect iCloud Mail via app-specific password. Password stored in vault only."""
    from .connectors.store import ConnectorStore
    from .connectors.models import ConnectedAccount
    import re as _re
    import uuid as _uuid
    from datetime import datetime, timezone as _tz
    import json as _json

    email = (body.email or "").strip()
    app_password = (body.app_password or "").strip()

    if not email or not _re.match(r"[^@]+@[^@]+\.[^@]+", email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if not app_password:
        raise HTTPException(status_code=400, detail="app_password is required")
    # Basic app-specific password format: xxxx-xxxx-xxxx-xxxx
    if len(app_password) < 8:
        raise HTTPException(status_code=400, detail="app_password too short")

    account_id = f"icloud-{_uuid.uuid4().hex[:12]}"
    now = datetime.now(_tz.utc).isoformat()
    token_str = _json.dumps({"email": email, "app_password": app_password})

    account = ConnectedAccount(
        account_id=account_id,
        user_id="local",
        provider="icloud",
        display_email=email,
        status="connected",
        scopes=[],
        capabilities=["mail.read", "mail.search"],
        created_at=now,
        updated_at=now,
    )
    store = ConnectorStore()
    store.save_account(account, token=token_str)
    return {"ok": True, "account_id": account_id, "provider": "icloud",
            "display_email": email, "status": "connected",
            "note": "App password stored in local vault only. Use /warden/mail/search to test."}


# ─── Mail endpoints ───────────────────────────────────────────────────────────

@mcharness_router.get("/warden/mail/accounts")
def get_warden_mail_accounts():
    """List connected mail accounts (no tokens returned)."""
    from .connectors.store import ConnectorStore
    from .connectors.registry import PROVIDERS
    all_accounts = ConnectorStore().list_accounts(redact=True)
    mail_providers = {"gmail", "outlook", "icloud"}
    mail_accounts = [a for a in all_accounts
                     if a.get("provider") in mail_providers]
    return {"ok": True, "accounts": mail_accounts, "count": len(mail_accounts)}


@mcharness_router.get("/warden/mail/search")
def get_warden_mail_search(account_id: str, q: str = "", limit: int = 10):
    """Search mail in a connected account. Returns summaries only."""
    from .connectors.store import ConnectorStore
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id required")
    if limit < 1 or limit > 50:
        limit = 10

    store = ConnectorStore()
    acc = store.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")

    provider_id = acc.get("provider", "")
    query = (q or "").strip() or "ALL"

    try:
        if provider_id == "icloud":
            from .mail.icloud import build_icloud_provider
            provider = build_icloud_provider(account_id)
            if not provider:
                raise HTTPException(status_code=422, detail="iCloud credentials not found in vault")
        elif provider_id == "gmail":
            # Try IMAP app-password first (primary), fall back to OAuth token
            from .mail.gmail_imap import build_gmail_imap_provider
            provider = build_gmail_imap_provider(account_id)
            if not provider:
                from .mail.gmail import build_gmail_provider
                provider = build_gmail_provider(account_id)
            if not provider:
                raise HTTPException(status_code=422, detail="Gmail not connected — use Settings to connect with App Password")
        else:
            raise HTTPException(status_code=422, detail=f"Mail search not supported for provider: {provider_id}")

        summaries = provider.search(query, limit=limit)
        return {"ok": True, "account_id": account_id, "provider": provider_id,
                "query": query, "count": len(summaries),
                "messages": [s.to_dict() for s in summaries]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mail search error: {type(e).__name__}: {e}")


@mcharness_router.get("/warden/mail/messages/{account_id}/{message_id:path}")
def get_warden_mail_message(account_id: str, message_id: str):
    """Read a mail message by ID. Returns normalized body_text (no HTML, no raw tokens)."""
    from .connectors.store import ConnectorStore
    store = ConnectorStore()
    acc = store.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")

    provider_id = acc.get("provider", "")
    try:
        if provider_id == "icloud":
            from .mail.icloud import build_icloud_provider
            provider = build_icloud_provider(account_id)
            if not provider:
                raise HTTPException(status_code=422, detail="iCloud credentials not found in vault")
        elif provider_id == "gmail":
            from .mail.gmail_imap import build_gmail_imap_provider
            provider = build_gmail_imap_provider(account_id)
            if not provider:
                from .mail.gmail import build_gmail_provider
                provider = build_gmail_provider(account_id)
            if not provider:
                raise HTTPException(status_code=422, detail="Gmail not connected — use Settings to connect with App Password")
        else:
            raise HTTPException(status_code=422, detail=f"Mail read not supported for: {provider_id}")

        msg = provider.read_message(message_id)
        return {"ok": True, "message": msg.to_dict(include_html=False)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mail read error: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Warden Brain — local vault + Google hybrid
# ---------------------------------------------------------------------------

class BrainWriteNoteRequest(BaseModel):
    title: str
    body: str
    tags: list[str] = []
    filename: Optional[str] = None


class BrainAskRequest(BaseModel):
    question: str
    limit: int = 6


class BrainMirrorRequest(BaseModel):
    dry_run: bool = True
    source_ids: list[str] = []
    limit: int = 50


class BrainProviderConfigSaveRequest(BaseModel):
    pass  # config is via env only; this endpoint just reads status


@mcharness_router.get("/warden/brain/health")
def get_brain_health():
    """Brain health: local vault + Google provider status."""
    from .brain import local_provider, google_provider
    local_st = local_provider.status()
    google_st = google_provider.status()
    return {
        "ok": True,
        "local": local_st,
        "google": google_st,
        "hybrid_enabled": google_provider.is_enabled() and google_provider.is_configured(),
    }


@mcharness_router.get("/warden/brain/providers")
def get_brain_providers():
    """List brain providers and their configuration status."""
    from .brain import local_provider, google_provider
    return {
        "ok": True,
        "providers": [
            {
                "provider_id": "local",
                "display_name": "Local Brain (Obsidian-compatible vault)",
                "free": True,
                "status": local_provider.status(),
            },
            {
                "provider_id": "google_discovery_engine",
                "display_name": "Google Brain (Vertex AI Search)",
                "free": False,
                "status": google_provider.status(),
            },
        ],
    }


@mcharness_router.post("/warden/brain/init-vault")
def post_brain_init_vault():
    """Initialize the local Markdown vault directory structure."""
    from .brain.vault import init_vault
    result = init_vault()
    return {"ok": True, **result}


@mcharness_router.post("/warden/brain/reindex")
def post_brain_reindex():
    """Scan vault and reindex all Markdown sources into SQLite FTS."""
    from .brain import local_provider
    result = local_provider.reindex()
    return {"ok": True, **result}


@mcharness_router.get("/warden/brain/sources")
def get_brain_sources(limit: int = 50):
    """List indexed brain sources."""
    from .brain.index import list_sources
    sources = list_sources(limit=limit)
    return {"ok": True, "sources": sources, "count": len(sources)}


@mcharness_router.get("/warden/brain/search")
def get_brain_search(q: str = "", limit: int = 10):
    """Hybrid search: local FTS + Google (if enabled)."""
    if not q:
        raise HTTPException(status_code=400, detail="q is required")
    from .brain import hybrid
    results = hybrid.search(q, limit=limit)
    return {"ok": True, "query": q, "results": results, "count": len(results)}


@mcharness_router.post("/warden/brain/ask")
def post_brain_ask(body: BrainAskRequest):
    """Hybrid ask: extractive answer with citations from local + Google."""
    from .brain import hybrid
    answer = hybrid.answer(body.question, limit=body.limit)
    return {"ok": True, **answer.to_dict()}


@mcharness_router.post("/warden/brain/write-note")
def post_brain_write_note(body: BrainWriteNoteRequest):
    """Write a new Markdown note to the vault inbox."""
    from .brain.vault import write_note
    try:
        result = write_note(
            title=body.title,
            body=body.body,
            tags=body.tags or [],
            filename=body.filename,
        )
        return {"ok": True, **result}
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class BrainIngestRequest(BaseModel):
    url: str
    title: str = ""
    source_type: str = "webpage"  # webpage | selection | youtube | pdf
    content_text: str = ""
    selected_text: str = ""
    channel: str = ""
    description: str = ""
    tags: list[str] = []
    local_only: bool = False


@mcharness_router.post("/warden/brain/ingest")
def post_brain_ingest(body: BrainIngestRequest):
    """Ingest a webpage, selected text, YouTube video, or PDF URL into the Brain vault."""
    from .brain import ingest as brain_ingest
    try:
        if body.source_type == "selection":
            if not body.selected_text:
                raise HTTPException(status_code=400, detail="selected_text required for source_type=selection")
            result = brain_ingest.ingest_selection(
                url=body.url,
                title=body.title or body.url,
                selected_text=body.selected_text,
                tags=body.tags or [],
                local_only=body.local_only,
            )
        elif body.source_type == "youtube":
            # Fetch transcript from API if not provided
            transcript = body.content_text
            if not transcript:
                yt = brain_ingest.fetch_youtube_transcript(body.url)
                transcript = yt.get("transcript", "")
            result = brain_ingest.ingest_youtube(
                url=body.url,
                title=body.title or body.url,
                channel=body.channel,
                description=body.description,
                transcript=transcript,
                tags=body.tags or [],
                local_only=body.local_only,
            )
        elif body.source_type == "pdf":
            result = brain_ingest.ingest_pdf(
                url=body.url,
                title=body.title,
                tags=body.tags or [],
                local_only=body.local_only,
            )
        else:
            # webpage (default)
            if not (body.content_text or body.selected_text):
                raise HTTPException(status_code=400, detail="content_text or selected_text required")
            result = brain_ingest.ingest_webpage(
                url=body.url,
                title=body.title or body.url,
                content_text=body.content_text,
                selected_text=body.selected_text,
                tags=body.tags or [],
                local_only=body.local_only,
            )
        if not result.get("ok"):
            return {"ok": False, "reason": result.get("error", "Ingest failed"), **result}
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@mcharness_router.post("/warden/brain/google/mirror")
def post_brain_google_mirror(body: BrainMirrorRequest):
    """Mirror local vault sources to Google Discovery Engine."""
    from .brain import google_provider
    from .brain.mirror import mirror_sources
    if not google_provider.is_enabled():
        return {
            "ok": False,
            "reason": "Google Brain not enabled. Set WARDEN_GOOGLE_BRAIN_ENABLED=1.",
            "dry_run": body.dry_run,
        }
    result = mirror_sources(
        source_ids=body.source_ids or None,
        limit=body.limit,
        dry_run=body.dry_run,
    )
    return {"ok": True, **result}


@mcharness_router.get("/warden/brain/google/mirror-status")
def get_brain_mirror_status():
    """Return mirror sync status for all sources."""
    from .brain.mirror import mirror_status
    result = mirror_status()
    return {"ok": True, **result}


@mcharness_router.get("/warden/brain/google/status")
def get_brain_google_status():
    """Google Brain provider status and configuration."""
    from .brain import google_provider
    return {"ok": True, **google_provider.status()}


@mcharness_router.post("/warden/brain/google/verify")
def post_brain_google_verify():
    """Verify Google Brain credentials with a lightweight search."""
    from .brain import google_provider
    result = google_provider.verify_config()
    return {"ok": result["ok"], **result}
