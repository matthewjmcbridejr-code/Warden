"""Thin client over existing Warden agent/session capabilities.

Wraps agent_registry.list_all_agents (agents) and agent_dispatcher's board
task iteration (sessions == in-flight dispatched tasks) rather than
reimplementing anything. For capabilities with no existing safe write
endpoint (e.g. "stop a running session"), returns a dry-run
"executor not implemented" response instead of guessing at an unsafe action.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

DEFAULT_SESSION_TAIL_LINES = 40
DEFAULT_ROOT = Path("~/.local/share/warden/agents").expanduser()


class WardenClient:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or DEFAULT_ROOT

    # -- agents -------------------------------------------------------------

    def list_agents(self) -> dict:
        try:
            from ..agent_registry import list_all_agents
            agents = list_all_agents(self.root, codex_runner_ready=False, private_only=True)
            return {
                "ok": True,
                "short_summary": f"{len(agents)} agent(s) registered.",
                "key_fields": {"count": len(agents)},
                "raw": agents,
            }
        except Exception as exc:
            return {"ok": False, "short_summary": f"Could not list agents: {exc}", "key_fields": {}}

    # -- sessions (dispatched board tasks currently claimed/running) --------

    def list_sessions(self, limit: int = 10) -> dict:
        try:
            from ..agent_dispatcher import _iter_tasks_by_status
            sessions = []
            for status in ("claimed", "queued", "draft"):
                for task, _path in _iter_tasks_by_status(status):
                    sessions.append({
                        "task_id": task.get("task_id"),
                        "title": task.get("title"),
                        "agent": task.get("agent"),
                        "status": status,
                        "updated_at": task.get("updated_at"),
                    })
            sessions = sessions[:limit]
            return {
                "ok": True,
                "short_summary": f"{len(sessions)} active session(s)." if sessions else "No active sessions.",
                "key_fields": {"count": len(sessions)},
                "raw": sessions,
            }
        except Exception as exc:
            return {"ok": False, "short_summary": f"Could not list sessions: {exc}", "key_fields": {}}

    def session_tail(self, task_id: str, max_lines: int = DEFAULT_SESSION_TAIL_LINES) -> dict:
        """Return the last N lines of a dispatched session's log, capped."""
        try:
            from ..agent_dispatcher import load_config
            cfg = load_config()
            log_dir = Path(cfg.get("log_dir", "~/.local/share/warden-agent-runs")).expanduser()
            matches = sorted(log_dir.glob(f"{task_id}_*.log"))
            if not matches:
                return {"ok": False, "short_summary": f"No log found for session {task_id}.", "key_fields": {}}
            log_path = matches[-1]
            lines = log_path.read_text(errors="replace").splitlines()
            tail = lines[-max_lines:]
            return {
                "ok": True,
                "short_summary": f"Last {len(tail)} line(s) of {task_id}.",
                "key_fields": {"lines": len(tail)},
                "artifact_path": str(log_path),
                "raw": tail,
            }
        except Exception as exc:
            return {"ok": False, "short_summary": f"Could not tail session: {exc}", "key_fields": {}}

    # -- status ---------------------------------------------------------------

    def status(self) -> dict:
        agents = self.list_agents()
        sessions = self.list_sessions()
        return {
            "ok": True,
            "short_summary": f"{agents.get('key_fields', {}).get('count', 0)} agents, "
                              f"{sessions.get('key_fields', {}).get('count', 0)} active sessions.",
            "key_fields": {
                "agents": agents.get("key_fields", {}).get("count", 0),
                "sessions": sessions.get("key_fields", {}).get("count", 0),
            },
        }

    # -- stop session (no safe executor exists yet) --------------------------

    def stop_session(self, session_match: str) -> dict:
        """Attempt to stop a running session by fuzzy match on task_id/title.

        There is no existing safe "kill a dispatched agent process" endpoint
        in agent_dispatcher.py (it launches via subprocess.run and blocks
        until completion/timeout — no supervised handle is kept for a
        resident process to signal). Rather than guess at an unsafe kill
        path, this always returns a dry-run response.
        """
        sessions = self.list_sessions().get("raw") or []
        match = None
        for s in sessions:
            if session_match.lower() in str(s.get("task_id", "")).lower() or \
               session_match.lower() in str(s.get("title", "")).lower():
                match = s
                break
        if match is None:
            return {
                "ok": False,
                "short_summary": f"No active session matched {session_match!r}.",
                "key_fields": {},
            }
        return {
            "ok": False,
            "short_summary": f"executor not implemented: cannot safely stop session {match.get('task_id')} "
                              "(no supervised process handle exists in agent_dispatcher). Dry-run only.",
            "key_fields": {"task_id": match.get("task_id"), "dry_run": True},
        }
