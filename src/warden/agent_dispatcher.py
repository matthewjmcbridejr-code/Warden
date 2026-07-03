"""Warden Local Agent Dispatcher.

Polls the Warden board for queued tasks targeted at local CLI agents
(cl, claude, codex) and dispatches them safely through an allowlist.

Usage:
    python -m warden.agent_dispatcher          # poll loop
    python -m warden.agent_dispatcher --once   # single poll pass (dry-run safe)
    python -m warden.agent_dispatcher --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .risk_gate import RiskGate, RiskGateViolation, RiskLevel

log = logging.getLogger("warden.dispatcher")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOARD_ROOT = Path(os.getenv("WARDEN_BOARD_ROOT", os.getenv("MCTABLE_BOARD_ROOT", "~/.local/share/warden/board"))).expanduser()
LOG_DIR = Path(os.getenv("WARDEN_AGENT_RUN_DIR", "~/.local/share/warden-agent-runs")).expanduser()
DISPATCH_CONFIG_PATH = Path(os.getenv("WARDEN_DISPATCH_CONFIG", "~/.config/warden/dispatch.json")).expanduser()

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "poll_interval_seconds": 10,
    "default_timeout_seconds": 1800,
    "log_dir": str(LOG_DIR),
    "allowed_repo_roots": [
        "/home/matt/Documents/Warden",
        "/home/matt/workspaces/warden",
        "/home/matt/workspaces/marius-core",
        "/home/matt/workspaces/grademy",
    ],
    "agents": {
        "cl": {
            "enabled": True,
            "command_template": ["cl", "--prompt-file", "{prompt_file}"],
        },
        "codex": {
            "enabled": True,
            "command_template": ["codex", "exec", "--file", "{prompt_file}"],
        },
        "claude": {
            "enabled": False,
            "command_template": ["claude", "--file", "{prompt_file}"],
        },
    },
}

DISPATCHABLE_STATUSES = {"queued", "draft"}
DISPATCHABLE_AGENTS = {"cl", "claude", "codex", "any"}


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config() -> Dict[str, Any]:
    if DISPATCH_CONFIG_PATH.exists():
        try:
            return {**DEFAULT_CONFIG, **json.loads(DISPATCH_CONFIG_PATH.read_text())}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Board access (read-only mirror of brain_mcp_server board helpers)
# ---------------------------------------------------------------------------

def _iter_tasks_by_status(status: str):
    d = BOARD_ROOT / "tasks" / status
    if not d.exists():
        return
    for f in sorted(d.glob("*.json")):
        try:
            yield json.loads(f.read_text()), f
        except Exception:
            continue


def _find_task(task_id: str):
    for status_dir in (BOARD_ROOT / "tasks").iterdir():
        candidate = status_dir / f"{task_id}.json"
        if candidate.exists():
            try:
                return json.loads(candidate.read_text()), candidate
            except Exception:
                pass
    return None, None


def _move_task(src_path: Path, dest_status: str, task: Dict[str, Any]) -> Path:
    dest_dir = BOARD_ROOT / "tasks" / dest_status
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src_path.name
    task["status"] = dest_status
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    dest.write_text(json.dumps(task, indent=2))
    src_path.unlink(missing_ok=True)
    return dest


def _write_activity(entry: Dict[str, Any]) -> None:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    activity_dir = BOARD_ROOT / "activity" / date_str
    activity_dir.mkdir(parents=True, exist_ok=True)
    with (activity_dir / "dispatcher.jsonl").open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Prompt file builder
# ---------------------------------------------------------------------------

def build_prompt_file(task: Dict[str, Any], context: str = "") -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())[:8]
    prompt_path = LOG_DIR / f"task_{task['task_id']}_{run_id}.prompt.md"

    lines = [
        "# Warden Dispatched Task",
        "",
        f"Task ID: {task['task_id']}",
        f"Title: {task.get('title', '')}",
        f"Project: {task.get('project', '')}",
        f"Priority: {task.get('priority', 'medium')}",
        f"Branch: {task.get('branch', '')}",
        f"Agent: {task.get('agent', '')}",
        "",
        "## Safety Rules",
        "",
        "- Do not touch secrets or .env files",
        "- Do not deploy or start live services",
        "- Do not send email or messages",
        "- Do not delete Notion records",
        "- Do not mutate GitHub remote/default branch without explicit approval",
        "- Do not run arbitrary shell commands",
        "- Write operations require a branch name",
        "- Every run must end with proof, failure, decision, or handoff",
        "",
        "## Task Description",
        "",
        task.get("description", task.get("body", "")),
        "",
    ]

    if context:
        lines += ["## Warden Context Pack", "", context, ""]

    lines += [
        "## Required Closeout",
        "",
        "You must end with one of:",
        "- **proof** — what you completed and verified",
        "- **failure** — what blocked you and why",
        "- **decision** — architectural choice you made",
        "- **handoff** — next agent and what to do",
        "",
        "Include: files inspected, files changed, commands run, test result, exact next action.",
    ]

    prompt_path.write_text("\n".join(lines))
    return prompt_path


# ---------------------------------------------------------------------------
# Dispatcher core
# ---------------------------------------------------------------------------

class DispatchResult:
    def __init__(self, task_id: str, run_id: str, success: bool, summary: str, log_path: Optional[Path] = None):
        self.task_id = task_id
        self.run_id = run_id
        self.success = success
        self.summary = summary
        self.log_path = log_path
        # Workspace Authority fields — populated when dispatch is blocked by drift
        self.workspace_drift: bool = False
        self.canonical_repo: Optional[str] = None
        self.next_action: Optional[str] = None


class AgentDispatcher:
    def __init__(self, config: Optional[Dict[str, Any]] = None, dry_run: bool = False) -> None:
        self.config = config or load_config()
        self.dry_run = dry_run
        self.gate = RiskGate(max_level=RiskLevel.safe_write)
        self._log_dir = Path(self.config.get("log_dir", str(LOG_DIR))).expanduser()

    def _agent_config(self, agent_id: str) -> Optional[Dict[str, Any]]:
        agents = self.config.get("agents", {})
        return agents.get(agent_id)

    def _is_agent_enabled(self, agent_id: str) -> bool:
        cfg = self._agent_config(agent_id)
        if not cfg:
            return False
        return bool(cfg.get("enabled", False))

    def _command_for_agent(self, agent_id: str, prompt_file: Path) -> Optional[List[str]]:
        cfg = self._agent_config(agent_id)
        if not cfg:
            return None
        template = cfg.get("command_template", [])
        return [t.replace("{prompt_file}", str(prompt_file)) for t in template]

    def _repo_path_allowed(self, task: Dict[str, Any]) -> bool:
        repo = task.get("repo") or task.get("repo_path") or ""
        if not repo:
            return True  # no repo constraint — allowed
        allowed = self.config.get("allowed_repo_roots", [])
        return any(str(repo).startswith(root) for root in allowed)

    def _workspace_preflight(self, task: Dict[str, Any], run_id: str) -> Optional[DispatchResult]:
        """Block dispatch if agent would be operating in a non-canonical worktree."""
        task_id = task["task_id"]
        project_id = task.get("project_id") or task.get("project") or "warden"
        # Prefer repo_path from task; fall back to current process cwd
        cwd = task.get("repo_path") or task.get("workspace_path") or os.getcwd()

        try:
            from .workspace_authority import detect_workspace_drift
            drift = detect_workspace_drift(project_id, cwd=cwd)
        except Exception as exc:
            # workspace_authority unavailable — log and allow (don't block on import error)
            log.warning("workspace_authority unavailable, skipping preflight: %s", exc)
            return None

        if drift.get("drifted") or not drift.get("safe_to_edit", True):
            canonical = drift.get("matched_worktree") or cwd
            try:
                from .workspace_authority import get_canonical_repo
                canonical = get_canonical_repo(project_id) or canonical
            except Exception:
                pass

            warning_msg = (
                f"[WorkspaceAuthority] BLOCKED: task {task_id!r} targets {cwd!r} "
                f"which is not canonical for project {project_id!r}. "
                f"Use {canonical!r}."
            )
            log.warning(warning_msg)
            _write_activity({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "workspace_drift_blocked",
                "task_id": task_id,
                "project_id": project_id,
                "cwd": cwd,
                "canonical": canonical,
                "run_id": run_id,
                "warning": warning_msg,
            })
            result = DispatchResult(task_id, run_id, False, warning_msg)
            result.canonical_repo = canonical
            result.workspace_drift = True
            result.next_action = f"Switch to {canonical!r} before running this task."
            return result

        return None  # preflight passed

    def dispatch_task(self, task: Dict[str, Any], src_path: Path) -> DispatchResult:
        task_id = task["task_id"]
        agent = task.get("agent", "any")
        run_id = str(uuid.uuid4())[:8]

        # Workspace Authority preflight — block non-canonical cwds
        blocked = self._workspace_preflight(task, run_id)
        if blocked is not None:
            return blocked

        # Resolve agent
        target_agent: Optional[str] = None
        if agent in ("any", ""):
            for a_id in self.config.get("agents", {}):
                if self._is_agent_enabled(a_id):
                    target_agent = a_id
                    break
        elif agent in self.config.get("agents", {}):
            target_agent = agent

        if not target_agent or not self._is_agent_enabled(target_agent):
            return DispatchResult(task_id, run_id, False, f"No enabled agent for {agent!r}")

        if not self._repo_path_allowed(task):
            return DispatchResult(task_id, run_id, False, "Repo path not in allowed list")

        # Risk gate: dispatching is a safe_write action
        try:
            self.gate.check("dispatch_task")
        except RiskGateViolation as e:
            return DispatchResult(task_id, run_id, False, str(e))

        # Build prompt file
        prompt_file = build_prompt_file(task)
        cmd = self._command_for_agent(target_agent, prompt_file)
        if not cmd:
            return DispatchResult(task_id, run_id, False, f"No command template for {target_agent!r}")

        log_path = self._log_dir / f"{task_id}_{run_id}.log"

        if self.dry_run:
            summary = f"[dry-run] would run: {shlex.join(cmd)} → {log_path}"
            log.info(summary)
            return DispatchResult(task_id, run_id, True, summary, log_path)

        # Claim task
        _move_task(src_path, "claimed", task)
        _write_activity({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "claimed",
            "task_id": task_id,
            "agent": target_agent,
            "run_id": run_id,
        })

        # Launch
        self._log_dir.mkdir(parents=True, exist_ok=True)
        timeout = self.config.get("default_timeout_seconds", 1800)
        try:
            with log_path.open("w") as log_fh:
                result = subprocess.run(
                    cmd,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                )
            success = result.returncode == 0
            summary = f"exit={result.returncode}"
        except subprocess.TimeoutExpired:
            success = False
            summary = f"timeout after {timeout}s"
        except FileNotFoundError:
            success = False
            summary = f"command not found: {cmd[0]!r}"

        # Move task to final status
        final_status = "completed" if success else "failed"
        _, current_path = _find_task(task_id)
        if current_path:
            _move_task(current_path, final_status, task)

        _write_activity({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "finished",
            "task_id": task_id,
            "agent": target_agent,
            "run_id": run_id,
            "success": success,
            "summary": summary,
            "log": str(log_path),
        })

        return DispatchResult(task_id, run_id, success, summary, log_path)

    def poll_once(self) -> List[DispatchResult]:
        results = []
        for status in DISPATCHABLE_STATUSES:
            for task, path in list(_iter_tasks_by_status(status)):
                agent = task.get("agent", "any")
                if agent not in DISPATCHABLE_AGENTS:
                    continue
                log.info("Dispatching task %s (agent=%s)", task.get("task_id"), agent)
                result = self.dispatch_task(task, path)
                results.append(result)
                if not result.success:
                    log.warning("Dispatch failed for %s: %s", result.task_id, result.summary)
        return results

    def run_loop(self) -> None:
        interval = self.config.get("poll_interval_seconds", 10)
        log.info("Dispatcher started — polling every %ss (dry_run=%s)", interval, self.dry_run)
        while True:
            try:
                self.poll_once()
            except Exception as exc:
                log.error("Poll error: %s", exc)
            time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(description="Warden Local Agent Dispatcher")
    parser.add_argument("--once", action="store_true", help="Run one poll pass then exit")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be dispatched, don't launch agents")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    dispatcher = AgentDispatcher(dry_run=args.dry_run)
    if not dispatcher.config.get("enabled", True):
        log.info("Dispatcher is disabled in config. Exiting.")
        sys.exit(0)

    if args.once or args.dry_run:
        results = dispatcher.poll_once()
        print(f"Dispatched {len(results)} task(s)")
        for r in results:
            status = "OK" if r.success else "FAIL"
            print(f"  [{status}] {r.task_id} — {r.summary}")
    else:
        dispatcher.run_loop()


if __name__ == "__main__":
    _main()
