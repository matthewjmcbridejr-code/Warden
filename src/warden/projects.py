"""Warden Project Command Center — projects + worktrees CRUD."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

import os

PROJECTS_ROOT = Path(os.getenv("MCHARNESS_DATA_ROOT", "_mctable")) / "projects"
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class WardenProject(BaseModel):
    project_id: str
    name: str
    repo_path: str
    default_branch: str = "main"
    worktree_root: Optional[str] = None
    agent_ids: List[str] = Field(default_factory=list)
    template_ids: List[str] = Field(default_factory=list)
    brain_tags: List[str] = Field(default_factory=list)
    status: Literal["active", "archived"] = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("project_id")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not SAFE_SLUG.match(v):
            raise ValueError(f"project_id must be a safe slug (a-z0-9_-): {v!r}")
        return v


class WardenWorktree(BaseModel):
    worktree_id: str
    project_id: str
    branch: str
    path: str
    agent_id: Optional[str] = None
    status: Literal["idle", "running", "waiting_proof", "merged", "abandoned"] = "idle"
    run_id: Optional[str] = None
    bootstrapped: bool = False
    proof_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _project_dir(project_id: str) -> Path:
    return PROJECTS_ROOT / project_id


def _load_project(project_id: str) -> WardenProject:
    path = _project_dir(project_id) / "project.json"
    if not path.exists():
        raise HTTPException(404, f"Project not found: {project_id}")
    return WardenProject(**json.loads(path.read_text()))


def _save_project(project: WardenProject) -> None:
    d = _project_dir(project.project_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.json").write_text(project.model_dump_json(indent=2))


def _load_worktrees(project_id: str) -> List[WardenWorktree]:
    path = _project_dir(project_id) / "worktrees.json"
    if not path.exists():
        return []
    return [WardenWorktree(**w) for w in json.loads(path.read_text())]


def _save_worktrees(project_id: str, worktrees: List[WardenWorktree]) -> None:
    path = _project_dir(project_id) / "worktrees.json"
    path.write_text(json.dumps([w.model_dump(mode="json") for w in worktrees], indent=2))


def _list_all_projects() -> List[WardenProject]:
    if not PROJECTS_ROOT.exists():
        return []
    projects = []
    for d in sorted(PROJECTS_ROOT.iterdir()):
        pf = d / "project.json"
        if pf.exists():
            try:
                projects.append(WardenProject(**json.loads(pf.read_text())))
            except Exception:
                pass
    return projects


# ---------------------------------------------------------------------------
# WorktrunkAdapter (inline — thin enough to not warrant its own file)
# ---------------------------------------------------------------------------

class WorktreeInfo(BaseModel):
    path: str
    branch: str
    head: Optional[str] = None
    locked: bool = False


class WorktrunkAdapter:
    """Wraps `wt` CLI if available, falls back to raw git worktree commands."""

    def __init__(self) -> None:
        self._wt = shutil.which("wt")

    # -- list ----------------------------------------------------------------

    def list_worktrees(self, repo_path: str) -> List[WorktreeInfo]:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git worktree list failed: {result.stderr.strip()}")
        return _parse_porcelain(result.stdout)

    # -- create --------------------------------------------------------------

    def create_worktree(self, repo_path: str, branch: str, worktree_root: str) -> WorktreeInfo:
        if not SAFE_SLUG.match(re.sub(r"[^a-z0-9_-]", "-", branch.lower())):
            raise ValueError(f"Unsafe branch name: {branch!r}")
        worktree_path = str(Path(worktree_root) / branch)
        # -b creates new branch; if it already exists use --track
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch, worktree_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")
        return WorktreeInfo(path=worktree_path, branch=branch)

    # -- remove --------------------------------------------------------------

    def remove_worktree(self, repo_path: str, path: str) -> None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", path],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )


def _parse_porcelain(text: str) -> List[WorktreeInfo]:
    entries: List[WorktreeInfo] = []
    current: Dict[str, Any] = {}
    for line in text.splitlines():
        if line.startswith("worktree "):
            if current:
                entries.append(WorktreeInfo(**current))
            current = {"path": line[9:]}
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            branch = line[7:]
            current["branch"] = branch.removeprefix("refs/heads/")
        elif line == "locked":
            current["locked"] = True
    if current:
        entries.append(WorktreeInfo(**current))
    return entries


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/projects", tags=["projects"])
_adapter = WorktrunkAdapter()


# -- request bodies --

class ProjectCreateRequest(BaseModel):
    name: str
    repo_path: str
    project_id: Optional[str] = None  # auto-slug from name if omitted
    default_branch: str = "main"
    worktree_root: Optional[str] = None
    agent_ids: List[str] = Field(default_factory=list)
    brain_tags: List[str] = Field(default_factory=list)


class ProjectPatchRequest(BaseModel):
    name: Optional[str] = None
    agent_ids: Optional[List[str]] = None
    brain_tags: Optional[List[str]] = None
    worktree_root: Optional[str] = None
    status: Optional[Literal["active", "archived"]] = None


class WorktreeCreateRequest(BaseModel):
    branch: str
    agent_id: Optional[str] = None
    prompt: Optional[str] = None  # stored; used for bootstrap injection


class WorktreePatchRequest(BaseModel):
    status: Optional[Literal["idle", "running", "waiting_proof", "merged", "abandoned"]] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    proof_id: Optional[str] = None


# -- endpoints --

@router.get("/")
def list_projects() -> List[Dict[str, Any]]:
    return [p.model_dump(mode="json") for p in _list_all_projects()]


@router.post("/", status_code=201)
def create_project(req: ProjectCreateRequest) -> Dict[str, Any]:
    pid = req.project_id or re.sub(r"[^a-z0-9]+", "-", req.name.lower()).strip("-")
    if not SAFE_SLUG.match(pid):
        raise HTTPException(400, f"Invalid project_id slug: {pid!r}")
    if (_project_dir(pid) / "project.json").exists():
        raise HTTPException(409, f"Project already exists: {pid}")
    project = WardenProject(
        project_id=pid,
        name=req.name,
        repo_path=req.repo_path,
        default_branch=req.default_branch,
        worktree_root=req.worktree_root,
        agent_ids=req.agent_ids,
        brain_tags=req.brain_tags,
    )
    _save_project(project)
    return project.model_dump(mode="json")


@router.get("/{project_id}")
def get_project(project_id: str) -> Dict[str, Any]:
    return _load_project(project_id).model_dump(mode="json")


@router.patch("/{project_id}")
def patch_project(project_id: str, req: ProjectPatchRequest) -> Dict[str, Any]:
    project = _load_project(project_id)
    if req.name is not None:
        project.name = req.name
    if req.agent_ids is not None:
        project.agent_ids = list(dict.fromkeys(req.agent_ids))
    if req.brain_tags is not None:
        project.brain_tags = req.brain_tags
    if req.worktree_root is not None:
        project.worktree_root = req.worktree_root
    if req.status is not None:
        project.status = req.status
    project.updated_at = datetime.now(timezone.utc)
    _save_project(project)
    return project.model_dump(mode="json")


@router.get("/{project_id}/worktrees")
def list_worktrees(project_id: str) -> List[Dict[str, Any]]:
    project = _load_project(project_id)
    stored = {w.branch: w for w in _load_worktrees(project_id)}
    try:
        live = _adapter.list_worktrees(project.repo_path)
    except Exception:
        live = []
    live_branches = {w.branch for w in live}
    # Merge live git state with stored metadata
    result = []
    for wt in live:
        meta = stored.get(wt.branch)
        entry = meta.model_dump(mode="json") if meta else {
            "worktree_id": wt.branch,
            "project_id": project_id,
            "branch": wt.branch,
            "path": wt.path,
            "status": "idle",
        }
        entry["head"] = wt.head
        entry["locked"] = wt.locked
        result.append(entry)
    # Include stored worktrees not yet visible via git (e.g. recently created)
    for branch, meta in stored.items():
        if branch not in live_branches:
            result.append(meta.model_dump(mode="json"))
    return result


@router.post("/{project_id}/worktrees", status_code=201)
def create_worktree_endpoint(project_id: str, req: WorktreeCreateRequest) -> Dict[str, Any]:
    import uuid
    project = _load_project(project_id)
    if not project.worktree_root:
        raise HTTPException(400, "Project has no worktree_root configured")
    Path(project.worktree_root).mkdir(parents=True, exist_ok=True)
    wt_info = _adapter.create_worktree(project.repo_path, req.branch, project.worktree_root)

    wt = WardenWorktree(
        worktree_id=str(uuid.uuid4()),
        project_id=project_id,
        branch=req.branch,
        path=wt_info.path,
        agent_id=req.agent_id,
        status="idle",
    )

    # Bootstrap injection
    if req.prompt:
        try:
            _inject_bootstrap(wt_info.path, project_id, req.prompt)
            wt.bootstrapped = True
        except Exception as e:
            pass  # non-fatal — worktree still created

    worktrees = _load_worktrees(project_id)
    worktrees.append(wt)
    _save_worktrees(project_id, worktrees)
    return wt.model_dump(mode="json")


@router.get("/{project_id}/recall")
def recall_for_project(project_id: str, query: str = "", kind: str = "", limit: int = 8) -> Dict[str, Any]:
    """Brain recall scoped to a project — for the Projects UI (no auth since local-only)."""
    _load_project(project_id)
    try:
        from src.warden.workbench import WorkbenchStore
        store = WorkbenchStore()
        memories = store.search_memories(query, scope=project_id, limit=max(1, min(limit, 20)))
        if kind:
            memories = [m for m in memories if m.kind == kind]
        return {
            "ok": True,
            "memories": [m.model_dump(mode="json") for m in memories],
        }
    except Exception as e:
        return {"ok": False, "memories": [], "error": str(e)}


@router.get("/{project_id}/bootstrap")
def bootstrap_for_project(project_id: str, task: str = "") -> Dict[str, Any]:
    """Bootstrap context for a project."""
    project = _load_project(project_id)
    try:
        from src.warden.workbench import WorkbenchStore
        store = WorkbenchStore()
        pack = store.build_memory_context_pack(project_id=project_id, user_prompt=task or "")
        # derive recommended_next_action from pack
        next_action = None
        if pack and hasattr(pack, "recommended_next_action"):
            next_action = pack.recommended_next_action
        elif pack and isinstance(pack, dict):
            next_action = pack.get("recommended_next_action")
        return {
            "ok": True,
            "project_id": project_id,
            "task": task,
            "recommended_next_action": next_action,
            "context": pack.model_dump(mode="json") if hasattr(pack, "model_dump") else pack,
        }
    except Exception as e:
        return {"ok": False, "recommended_next_action": None, "error": str(e)}


@router.patch("/{project_id}/worktrees/{worktree_id}")
def patch_worktree(project_id: str, worktree_id: str, req: WorktreePatchRequest) -> Dict[str, Any]:
    _load_project(project_id)
    worktrees = _load_worktrees(project_id)
    for wt in worktrees:
        if wt.worktree_id == worktree_id or wt.branch == worktree_id:
            if req.status is not None:
                wt.status = req.status
            if req.agent_id is not None:
                wt.agent_id = req.agent_id
            if req.run_id is not None:
                wt.run_id = req.run_id
            if req.proof_id is not None:
                wt.proof_id = req.proof_id
            wt.updated_at = datetime.now(timezone.utc)
            _save_worktrees(project_id, worktrees)
            return wt.model_dump(mode="json")
    raise HTTPException(404, f"Worktree not found: {worktree_id}")


# ---------------------------------------------------------------------------
# Bootstrap injection helper
# ---------------------------------------------------------------------------

def _inject_bootstrap(worktree_path: str, project_id: str, prompt: str) -> None:
    """Write .warden_context.json into the worktree."""
    try:
        from src.warden.personal_memory import load_profile
        profile = load_profile()
    except Exception:
        profile = {}

    packet = {
        "schema": "warden.bootstrap.v1",
        "project_id": project_id,
        "prompt": prompt,
        "operator": profile.get("name", "Matt"),
        "active_projects": profile.get("active_projects", []),
        "preferences": profile.get("preferences", {}),
        "injected_at": datetime.now(timezone.utc).isoformat(),
        "instructions": (
            "You are operating in a Warden-supervised worktree. "
            "When your task is complete, call warden_remember(kind='proof') to close the proof gate."
        ),
    }
    out = Path(worktree_path) / ".warden_context.json"
    out.write_text(json.dumps(packet, indent=2))
