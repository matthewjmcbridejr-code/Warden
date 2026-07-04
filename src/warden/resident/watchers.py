"""Watcher model + adapter for the resident agent.

Reuses memory_watcher.py's collection primitives where useful (file/shell/
chrome collectors) but defines its own lightweight Watcher record schema
since memory_watcher.py's WorkEvent/MemoryWriter model is oriented around
auto-capturing dev activity into workbench memories, not user-defined
recurring checks (DNS/website/email/agent/reminder).

Only notifies when last_result_hash changes (hash-based dedup) and applies
exponential backoff (via cadence multiplier) after repeated failures.
"""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

WATCHER_KINDS = ("dns", "website", "email", "agent", "reminder", "generic", "captain_dispatch")
WATCHER_STATUSES = ("active", "paused", "done", "error")

MAX_BACKOFF_MULTIPLIER = 8
DNS_LOOKUP_TIMEOUT = 5.0
HTTP_CHECK_TIMEOUT = 8.0
CAPTAIN_DISPATCH_STALL_SECONDS = 20 * 60
TMUX_CHECK_TIMEOUT = 2.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_result(result: Any) -> str:
    blob = json.dumps(result, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


@dataclass
class Watcher:
    id: str
    title: str
    kind: str  # dns | website | email | agent | reminder | generic
    query: str  # target: domain, url, session id, reminder text, etc.
    cadence_seconds: int = 3600
    last_checked_at: Optional[str] = None
    last_result: Optional[dict] = None
    last_result_hash: Optional[str] = None
    status: str = "active"
    notify_on: str = "change"  # change | always | error
    created_by: str = "resident"
    failure_count: int = 0
    created_at: str = field(default_factory=_now)

    def effective_cadence(self) -> int:
        """Cadence with exponential backoff applied after repeated failures."""
        multiplier = min(2 ** self.failure_count, MAX_BACKOFF_MULTIPLIER) if self.failure_count else 1
        return self.cadence_seconds * multiplier

    def due(self, now: Optional[datetime] = None) -> bool:
        if self.status != "active":
            return False
        if self.last_checked_at is None:
            return True
        now = now or datetime.now(timezone.utc)
        last = datetime.fromisoformat(self.last_checked_at)
        return (now - last).total_seconds() >= self.effective_cadence()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Watcher":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def check_dns(domain: str, *, timeout: float = DNS_LOOKUP_TIMEOUT) -> dict:
    """Resolve NS/A/CNAME for a domain with a bounded timeout.

    Prefers dnspython if installed; falls back to `dig` subprocess, then
    socket.gethostbyname for a minimal A-record check. Never raises.
    """
    result: dict[str, Any] = {"domain": domain, "ns": [], "a": [], "cname": [], "error": None}
    try:
        import dns.resolver  # type: ignore
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        resolver.timeout = timeout
        for rtype, key in (("NS", "ns"), ("A", "a"), ("CNAME", "cname")):
            try:
                answers = resolver.resolve(domain, rtype)
                result[key] = sorted(str(r).rstrip(".") for r in answers)
            except Exception:
                result[key] = []
        return result
    except ImportError:
        pass

    # Fallback: dig subprocess
    try:
        for rtype, key in (("NS", "ns"), ("A", "a"), ("CNAME", "cname")):
            proc = subprocess.run(
                ["dig", "+short", rtype, domain], capture_output=True, text=True, timeout=timeout
            )
            if proc.returncode == 0:
                result[key] = sorted({l.strip().rstrip(".") for l in proc.stdout.splitlines() if l.strip()})
        return result
    except FileNotFoundError:
        pass
    except Exception as exc:
        result["error"] = str(exc)
        return result

    # Last resort: plain socket A-record lookup
    try:
        socket.setdefaulttimeout(timeout)
        addr = socket.gethostbyname(domain)
        result["a"] = [addr]
    except Exception as exc:
        result["error"] = str(exc)
    return result


def check_website(url: str, *, timeout: float = HTTP_CHECK_TIMEOUT) -> dict:
    """Check HTTP status for a URL with a short timeout. Never raises."""
    result: dict[str, Any] = {"url": url, "status_code": None, "ok": False, "error": None}
    try:
        import requests  # type: ignore
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        result["status_code"] = resp.status_code
        result["ok"] = 200 <= resp.status_code < 400
    except ImportError:
        try:
            import urllib.request
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                result["status_code"] = resp.status
                result["ok"] = 200 <= resp.status < 400
        except Exception as exc:
            result["error"] = str(exc)
    except Exception as exc:
        result["error"] = str(exc)
    return result


def check_captain_dispatch(watcher: "Watcher") -> dict:
    """Poll a Captain-dispatched CLI run: tmux session gone => the process exited on its
    own (outcome=completed); still running past CAPTAIN_DISPATCH_STALL_SECONDS =>
    outcome=stalled. Never raises — the caller (Captain dispatch endpoint) decides what
    to do with the outcome (mark step passed/needs_review, auto-dispatch next step).
    """
    result: dict[str, Any] = {"outcome": "running"}
    try:
        payload = json.loads(watcher.query)
    except Exception:
        return {"outcome": "error", "error": "invalid watcher query payload"}
    result.update({
        "plan_id": payload.get("plan_id"),
        "step_id": payload.get("step_id"),
        "run_id": payload.get("run_id"),
        "lane_id": payload.get("lane_id"),
        "tmux_session_name": payload.get("tmux_session_name"),
    })
    tmux_name = str(payload.get("tmux_session_name") or "")
    if not tmux_name:
        result["outcome"] = "error"
        result["error"] = "watcher payload missing tmux_session_name"
        return result
    try:
        proc = subprocess.run(
            ["tmux", "has-session", "-t", tmux_name],
            capture_output=True, text=True, timeout=TMUX_CHECK_TIMEOUT,
        )
        has_session = proc.returncode == 0
    except Exception as exc:
        result["outcome"] = "error"
        result["error"] = str(exc)
        return result

    if not has_session:
        result["outcome"] = "completed"
        return result

    started_at = payload.get("started_at")
    if started_at:
        try:
            started = datetime.fromisoformat(started_at)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            result["elapsed_seconds"] = elapsed
            if elapsed > CAPTAIN_DISPATCH_STALL_SECONDS:
                result["outcome"] = "stalled"
        except Exception:
            pass
    return result


CheckFn = Callable[[Watcher], dict]

_CHECKERS: dict[str, CheckFn] = {
    "dns": lambda w: check_dns(w.query),
    "website": lambda w: check_website(w.query),
    "captain_dispatch": check_captain_dispatch,
}


class WatcherService:
    """Watcher lifecycle: create/list/run/update, backed by ResidentState."""

    def __init__(self, state) -> None:
        self.state = state

    def create(
        self,
        title: str,
        kind: str,
        query: str,
        *,
        cadence_seconds: int = 3600,
        notify_on: str = "change",
        created_by: str = "resident",
    ) -> Watcher:
        if kind not in WATCHER_KINDS:
            raise ValueError(f"unknown watcher kind: {kind}")
        watcher = Watcher(
            id=uuid.uuid4().hex[:12],
            title=title,
            kind=kind,
            query=query,
            cadence_seconds=cadence_seconds,
            notify_on=notify_on,
            created_by=created_by,
        )
        self.state.save_watcher(watcher.id, watcher.to_dict())
        return watcher

    def get(self, watcher_id: str) -> Optional[Watcher]:
        data = self.state.get_watcher(watcher_id)
        return Watcher.from_dict(data) if data else None

    def list(self, status: Optional[str] = None) -> list[Watcher]:
        watchers = [Watcher.from_dict(d) for d in self.state.list_watchers()]
        if status:
            watchers = [w for w in watchers if w.status == status]
        return watchers

    def pause(self, watcher_id: str) -> Optional[Watcher]:
        return self._update_status(watcher_id, "paused")

    def resume(self, watcher_id: str) -> Optional[Watcher]:
        return self._update_status(watcher_id, "active")

    def _update_status(self, watcher_id: str, status: str) -> Optional[Watcher]:
        watcher = self.get(watcher_id)
        if watcher is None:
            return None
        watcher.status = status
        self.state.save_watcher(watcher.id, watcher.to_dict())
        return watcher

    def run(self, watcher_id: str, *, force: bool = False) -> tuple[Optional[Watcher], bool]:
        """Run a single watcher check. Returns (watcher, should_notify).

        should_notify is True only when the result hash changed (or notify_on
        is 'always', or notify_on is 'error' and this run errored).
        """
        watcher = self.get(watcher_id)
        if watcher is None:
            return None, False
        if not force and not watcher.due():
            return watcher, False

        checker = _CHECKERS.get(watcher.kind)
        if checker is None:
            result = {"note": f"no automated checker for kind={watcher.kind}; manual/generic watcher"}
        else:
            try:
                result = checker(watcher)
            except Exception as exc:
                result = {"error": str(exc)}

        errored = bool(result.get("error"))
        new_hash = _hash_result(result)
        changed = new_hash != watcher.last_result_hash

        watcher.last_result = result
        watcher.last_checked_at = _now()
        if errored:
            watcher.failure_count += 1
            watcher.status = "error" if watcher.failure_count >= 5 else watcher.status
        else:
            watcher.failure_count = 0

        should_notify = False
        if watcher.notify_on == "always":
            should_notify = True
        elif watcher.notify_on == "error":
            should_notify = errored
        else:  # "change" — hash-based dedup
            should_notify = changed and not self.state.has_notified(watcher.id, new_hash)

        watcher.last_result_hash = new_hash
        self.state.save_watcher(watcher.id, watcher.to_dict())

        if should_notify and watcher.notify_on == "change":
            self.state.mark_notified(watcher.id, new_hash)

        return watcher, should_notify

    def run_due(self) -> list[tuple[Watcher, bool]]:
        """Run every active watcher that's due. Returns [(watcher, notified)]."""
        out = []
        for watcher in self.list(status="active"):
            if watcher.due():
                w, notify = self.run(watcher.id, force=True)
                if w:
                    out.append((w, notify))
        return out

    def delete(self, watcher_id: str) -> bool:
        existed = self.get(watcher_id) is not None
        self.state.delete_watcher(watcher_id)
        return existed
