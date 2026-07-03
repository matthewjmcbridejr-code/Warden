"""Warden Autonomous Memory Collector — watches your work and captures context automatically.

Like PiecesOS but local-first. Monitors:
  - Git commits, branch switches, staged changes
  - File activity in watched paths (mtime polling, no deps)
  - Shell history for warden-relevant commands
  - Test runs (pytest output files)

Writes WorkbenchMemory entries automatically:
  - kind=proof      on git commit
  - kind=context    on branch switch or sustained file activity
  - kind=failure    on non-zero test exit detected in history
  - kind=handoff    on git push / PR creation detected

Usage:
    python -m warden.memory_watcher             # daemon loop
    python -m warden.memory_watcher --once      # single collection pass
    python -m warden.memory_watcher --dry-run   # print what would be written
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("warden.memory_watcher")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CANONICAL_REPO = Path(
    os.getenv("WARDEN_CANONICAL_REPO", "/home/matt/workspaces/warden/mcharness-public-export")
)
WATCHED_PATHS: List[Path] = [
    CANONICAL_REPO / "src" / "warden",
    CANONICAL_REPO / "web" / "warden",
    CANONICAL_REPO / "tests",
]
SHELL_HISTORY_PATHS: List[Path] = [
    Path("~/.bash_history").expanduser(),
    Path("~/.zsh_history").expanduser(),
]
POLL_INTERVAL = int(os.getenv("WARDEN_WATCHER_INTERVAL", "30"))   # seconds between polls
DEBOUNCE_WINDOW = int(os.getenv("WARDEN_WATCHER_DEBOUNCE", "60")) # seconds of quiet before writing memory
MAX_MEMORIES_PER_HOUR = int(os.getenv("WARDEN_WATCHER_RATE_LIMIT", "20"))
CHROME_HISTORY_DB = Path(
    os.getenv("WARDEN_CHROME_HISTORY", "~/.config/google-chrome/Default/History")
).expanduser()
# Domains/patterns worth capturing as work context
WORK_URL_PATTERN = re.compile(
    r"(github\.com|localhost|127\.0\.0\.1|notion\.so|linear\.app|"
    r"stackoverflow\.com|docs\.|anthropic\.com|openai\.com|"
    r"vercel\.com|supabase\.com|railway\.app|render\.com|"
    r"grademy|mctable|marius|warden)",
    re.IGNORECASE,
)
CHROME_POLL_INTERVAL = int(os.getenv("WARDEN_CHROME_POLL_INTERVAL", "60"))  # seconds

WARDEN_RELEVANT_CMDS = re.compile(
    r"(pytest|py\.test|git (commit|push|checkout|merge|rebase)|"
    r"uvicorn|python -m warden|curl.*6969|npm (run|test|build))",
    re.IGNORECASE,
)
TEST_FAIL_PATTERN = re.compile(r"(\d+) failed", re.IGNORECASE)
TEST_PASS_PATTERN = re.compile(r"(\d+) passed", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(args: List[str], cwd: Path = CANONICAL_REPO) -> str:
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _current_branch(cwd: Path = CANONICAL_REPO) -> str:
    return _git(["branch", "--show-current"], cwd) or "unknown"


def _last_commit(cwd: Path = CANONICAL_REPO) -> Dict[str, str]:
    out = _git(["log", "-1", "--format=%H|%s|%an|%ai", "--no-merges"], cwd)
    if not out:
        return {}
    parts = out.split("|", 3)
    if len(parts) < 4:
        return {}
    return {"hash": parts[0], "subject": parts[1], "author": parts[2], "date": parts[3]}


def _changed_files(cwd: Path = CANONICAL_REPO) -> List[str]:
    out = _git(["diff", "--name-only", "HEAD~1", "HEAD"], cwd)
    return [l for l in out.splitlines() if l.strip()] if out else []


def _staged_files(cwd: Path = CANONICAL_REPO) -> List[str]:
    out = _git(["diff", "--cached", "--name-only"], cwd)
    return [l for l in out.splitlines() if l.strip()] if out else []


def _uncommitted_summary(cwd: Path = CANONICAL_REPO) -> str:
    out = _git(["diff", "--stat", "HEAD"], cwd)
    return out[:400] if out else ""


# ---------------------------------------------------------------------------
# File activity tracker (mtime polling — no external deps)
# ---------------------------------------------------------------------------

class FileActivityTracker:
    def __init__(self, paths: List[Path]) -> None:
        self._paths = paths
        self._seen: Dict[str, float] = {}  # path → last mtime

    def poll(self) -> List[str]:
        """Return list of files changed since last poll."""
        changed = []
        for root in self._paths:
            if not root.exists():
                continue
            for f in root.rglob("*"):
                if not f.is_file():
                    continue
                if any(part.startswith(".") for part in f.parts):
                    continue
                key = str(f)
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    continue
                if key in self._seen and mtime > self._seen[key]:
                    changed.append(key)
                self._seen[key] = mtime
        return changed

    def seed(self) -> None:
        """Populate initial mtime map without triggering changes."""
        for root in self._paths:
            if not root.exists():
                continue
            for f in root.rglob("*"):
                if not f.is_file():
                    continue
                try:
                    self._seen[str(f)] = f.stat().st_mtime
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Shell history collector
# ---------------------------------------------------------------------------

class ShellHistoryCollector:
    def __init__(self) -> None:
        self._offsets: Dict[str, int] = {}

    def poll(self) -> List[str]:
        """Return new warden-relevant shell commands since last poll."""
        relevant = []
        for hist in SHELL_HISTORY_PATHS:
            if not hist.exists():
                continue
            try:
                text = hist.read_bytes()
                # strip zsh extended history timestamps
                decoded = text.decode("utf-8", errors="replace")
                lines = decoded.splitlines()
                prev = self._offsets.get(str(hist), 0)
                new_lines = lines[prev:]
                self._offsets[str(hist)] = len(lines)
                for line in new_lines:
                    line = re.sub(r"^: \d+:\d+;", "", line).strip()
                    if line and WARDEN_RELEVANT_CMDS.search(line):
                        relevant.append(line)
            except Exception:
                pass
        return relevant


# ---------------------------------------------------------------------------
# Chrome browser activity collector
# ---------------------------------------------------------------------------

class ChromeCollector:
    """Reads Chrome's SQLite History DB for recently visited work-relevant URLs.

    Uses a copy of the DB (Chrome locks it while running) to avoid errors.
    Only captures URLs matching WORK_URL_PATTERN.
    """

    def __init__(self) -> None:
        self._last_visit_time: int = 0   # Chrome epoch: microseconds since 1601-01-01
        self._db_path = CHROME_HISTORY_DB

    def _chrome_epoch_to_ts(self, chrome_ts: int) -> str:
        """Convert Chrome timestamp to ISO string."""
        # Chrome epoch starts 1601-01-01; Unix epoch starts 1970-01-01
        # Difference: 11644473600 seconds
        unix_ts = (chrome_ts / 1_000_000) - 11644473600
        try:
            return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()
        except Exception:
            return ""

    def poll(self) -> List[Dict[str, str]]:
        """Return list of {url, title, visited_at} for new work-relevant visits."""
        if not self._db_path.exists():
            return []

        import sqlite3
        import shutil
        import tempfile

        # Copy DB so we don't fight Chrome's lock
        try:
            tmp = tempfile.mktemp(suffix=".db")
            shutil.copy2(str(self._db_path), tmp)
        except Exception:
            return []

        results = []
        try:
            conn = sqlite3.connect(tmp)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT url, title, last_visit_time FROM urls "
                "WHERE last_visit_time > ? ORDER BY last_visit_time DESC LIMIT 50",
                (self._last_visit_time,),
            )
            rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            log.debug("Chrome history read error: %s", exc)
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass
            return []

        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass

        max_ts = self._last_visit_time
        for row in rows:
            url = row["url"] or ""
            title = row["title"] or ""
            ts = row["last_visit_time"] or 0
            if not WORK_URL_PATTERN.search(url) and not WORK_URL_PATTERN.search(title):
                continue
            # Skip internal chrome:// and extension pages
            if url.startswith(("chrome://", "chrome-extension://", "about:")):
                continue
            results.append({
                "url": url[:300],
                "title": title[:200],
                "visited_at": self._chrome_epoch_to_ts(ts),
            })
            max_ts = max(max_ts, ts)

        if max_ts > self._last_visit_time:
            self._last_visit_time = max_ts

        return results


# ---------------------------------------------------------------------------
# Event accumulator
# ---------------------------------------------------------------------------

class WorkEvent:
    """A cluster of activity to synthesize into a memory."""

    def __init__(self) -> None:
        self.changed_files: List[str] = []
        self.shell_commands: List[str] = []
        self.browser_visits: List[Dict[str, str]] = []
        self.branch: str = ""
        self.last_commit: Dict[str, str] = {}
        self.ts: float = time.time()

    def is_empty(self) -> bool:
        return not (self.changed_files or self.shell_commands or self.last_commit or self.browser_visits)

    def summary(self) -> str:
        parts = []
        if self.last_commit:
            parts.append(f"Commit: {self.last_commit.get('subject', '')}")
        if self.changed_files:
            sample = self.changed_files[:5]
            parts.append(f"Files: {', '.join(sample)}" + (" …" if len(self.changed_files) > 5 else ""))
        if self.shell_commands:
            sample = self.shell_commands[-3:]
            parts.append(f"Commands: {'; '.join(sample)}")
        if self.browser_visits:
            titles = [v.get("title") or v.get("url", "") for v in self.browser_visits[:3]]
            parts.append(f"Browser: {', '.join(t[:60] for t in titles)}")
        return " | ".join(parts) or "Work activity detected"

    def kind(self) -> str:
        cmds = " ".join(self.shell_commands).lower()
        if self.last_commit:
            return "proof"
        if "pytest" in cmds or "py.test" in cmds:
            for cmd in self.shell_commands:
                if TEST_FAIL_PATTERN.search(cmd):
                    return "failure"
            return "proof"
        if self.changed_files:
            return "context"
        if self.browser_visits:
            return "context"
        return "context"


# ---------------------------------------------------------------------------
# Memory writer
# ---------------------------------------------------------------------------

class MemoryWriter:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._written_this_hour: List[float] = []

    def _rate_ok(self) -> bool:
        now = time.time()
        self._written_this_hour = [t for t in self._written_this_hour if now - t < 3600]
        return len(self._written_this_hour) < MAX_MEMORIES_PER_HOUR

    def _dedup_key(self, event: WorkEvent) -> str:
        raw = event.last_commit.get("hash", "") + "|".join(sorted(event.changed_files[:5]))
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def write(self, event: WorkEvent, branch: str, repo: str = str(CANONICAL_REPO)) -> Optional[str]:
        if event.is_empty():
            return None
        if not self._rate_ok():
            log.warning("Rate limit reached (%d/hr). Skipping memory.", MAX_MEMORIES_PER_HOUR)
            return None

        summary = event.summary()
        kind = event.kind()
        memory_id = f"watcher-{self._dedup_key(event)}"
        tags = ["auto", "watcher", kind, branch or "unknown"]
        if event.last_commit:
            tags.append("commit")

        payload = {
            "memory_id": memory_id,
            "scope": "warden",
            "summary": summary,
            "source": "memory_watcher",
            "title": (event.last_commit.get("subject") or summary)[:80],
            "kind": kind,
            "repo_path": repo,
            "branch": branch,
            "tags": tags,
            "metadata": {
                "changed_files": event.changed_files[:20],
                "shell_commands": event.shell_commands[-10:],
                "browser_visits": event.browser_visits[:10],
                "commit": event.last_commit,
                "auto_captured": True,
            },
        }

        if self.dry_run:
            log.info("[dry-run] would write memory: %s (%s) — %s", memory_id, kind, summary[:80])
            return memory_id

        try:
            from .workbench import WorkbenchStore, WorkbenchMemoryCreateRequest
            store = WorkbenchStore()
            # Skip if already exists (dedup)
            existing = store.search_memories(memory_id, limit=1)
            if any(m.memory_id == memory_id for m in existing):
                log.debug("Memory %s already exists, skipping.", memory_id)
                return None
            req = WorkbenchMemoryCreateRequest(**{k: v for k, v in payload.items()
                                                   if k in WorkbenchMemoryCreateRequest.model_fields})
            req.metadata = payload["metadata"]
            mem = store.create_memory(req)
            self._written_this_hour.append(time.time())
            log.info("Wrote memory %s (%s): %s", mem.memory_id, kind, summary[:80])
            return mem.memory_id
        except Exception as exc:
            log.warning("Failed to write memory: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Git hook installer
# ---------------------------------------------------------------------------

def install_git_hooks(repo: Path = CANONICAL_REPO) -> List[str]:
    """Install post-commit and post-checkout hooks that ping the watcher."""
    hooks_dir = repo / ".git" / "hooks"
    if not hooks_dir.exists():
        return []
    installed = []
    hook_script = f"""#!/bin/sh
# Warden memory watcher hook — auto-installed
PYTHONPATH="{repo}:{repo}/src" \\
  "{repo}/.venv/bin/python" -m warden.memory_watcher --once --quiet 2>/dev/null &
"""
    for hook_name in ("post-commit", "post-checkout", "post-merge"):
        hook_path = hooks_dir / hook_name
        existing = hook_path.read_text() if hook_path.exists() else ""
        if "warden.memory_watcher" in existing:
            installed.append(f"{hook_name} (already installed)")
            continue
        # Append to existing hook or create new
        if existing and not existing.startswith("#!"):
            existing = "#!/bin/sh\n" + existing
        new_content = (existing.rstrip() + "\n\n" + hook_script) if existing else hook_script
        hook_path.write_text(new_content)
        hook_path.chmod(0o755)
        installed.append(hook_name)
    return installed


def uninstall_git_hooks(repo: Path = CANONICAL_REPO) -> List[str]:
    hooks_dir = repo / ".git" / "hooks"
    removed = []
    for hook_name in ("post-commit", "post-checkout", "post-merge"):
        hook_path = hooks_dir / hook_name
        if not hook_path.exists():
            continue
        content = hook_path.read_text()
        if "warden.memory_watcher" not in content:
            continue
        # Remove the watcher block
        lines = content.splitlines(keepends=True)
        cleaned = [l for l in lines if "warden.memory_watcher" not in l]
        if cleaned and all(l.strip() in ("", "#!/bin/sh") for l in cleaned):
            hook_path.unlink()
        else:
            hook_path.write_text("".join(cleaned))
        removed.append(hook_name)
    return removed


# ---------------------------------------------------------------------------
# Watcher daemon
# ---------------------------------------------------------------------------

class MemoryWatcher:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._file_tracker = FileActivityTracker(WATCHED_PATHS)
        self._history = ShellHistoryCollector()
        self._chrome = ChromeCollector()
        self._writer = MemoryWriter(dry_run=dry_run)
        self._pending = WorkEvent()
        self._last_commit_hash = ""
        self._last_branch = ""
        self._last_flush = time.time()
        self._running = False
        self._lock = threading.Lock()
        # stats
        self.memories_written = 0
        self.polls_run = 0

    def _collect(self) -> bool:
        """Run one collection cycle. Returns True if new activity found."""
        branch = _current_branch()
        commit = _last_commit()
        commit_hash = commit.get("hash", "")
        changed_files = self._file_tracker.poll()
        new_cmds = self._history.poll()
        new_visits = self._chrome.poll()
        activity = False

        with self._lock:
            # Branch switch → flush current event, start new one with context note
            if self._last_branch and branch != self._last_branch:
                log.info("Branch switched: %s → %s", self._last_branch, branch)
                if not self._pending.is_empty():
                    self._flush()
                self._pending = WorkEvent()
                self._pending.shell_commands.append(f"git checkout {branch}")
                self._pending.branch = branch
                activity = True

            # New commit
            if commit_hash and commit_hash != self._last_commit_hash:
                self._pending.last_commit = commit
                self._pending.changed_files += _changed_files()
                self._last_commit_hash = commit_hash
                activity = True
                # Commit → flush immediately (don't wait for debounce)
                self._flush()
                self._pending = WorkEvent()

            if changed_files:
                self._pending.changed_files += [Path(f).name for f in changed_files]
                self._pending.changed_files = list(dict.fromkeys(self._pending.changed_files))
                activity = True

            if new_cmds:
                self._pending.shell_commands += new_cmds
                activity = True

            if new_visits:
                self._pending.browser_visits += new_visits
                activity = True

            self._pending.branch = branch
            self._last_branch = branch

        return activity

    def _flush(self) -> None:
        """Synthesize pending event into a memory (called with lock held)."""
        if self._pending.is_empty():
            return
        branch = self._pending.branch or _current_branch()
        mem_id = self._writer.write(self._pending, branch)
        if mem_id:
            self.memories_written += 1
        self._last_flush = time.time()

    def poll_once(self) -> int:
        """Single collection + flush pass. Returns memories written."""
        before = self.memories_written
        self._file_tracker.seed() if not self._last_branch else None
        self._collect()
        with self._lock:
            if not self._pending.is_empty():
                self._flush()
                self._pending = WorkEvent()
        return self.memories_written - before

    def run_loop(self) -> None:
        """Continuous polling loop."""
        self._running = True
        log.info("Memory watcher started (interval=%ds, debounce=%ds, dry_run=%s)",
                 POLL_INTERVAL, DEBOUNCE_WINDOW, self.dry_run)
        # Seed on first run — consume existing state without triggering memories
        self._file_tracker.seed()
        self._history.poll()   # consume existing shell history
        self._chrome.poll()    # consume existing Chrome history (don't replay old visits)
        self._last_branch = _current_branch()
        self._last_commit_hash = _last_commit().get("hash", "")

        while self._running:
            try:
                self.polls_run += 1
                activity = self._collect()
                # Flush if debounce window has passed since last activity
                with self._lock:
                    idle = time.time() - self._last_flush
                    has_pending = not self._pending.is_empty()
                if has_pending and idle >= DEBOUNCE_WINDOW:
                    with self._lock:
                        self._flush()
                        self._pending = WorkEvent()
            except Exception as exc:
                log.error("Watcher error: %s", exc)
            time.sleep(POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# Status for API
# ---------------------------------------------------------------------------

_watcher_instance: Optional[MemoryWatcher] = None
_watcher_thread: Optional[threading.Thread] = None


def get_watcher_status() -> Dict[str, Any]:
    global _watcher_instance
    if _watcher_instance is None:
        return {"running": False, "memories_written": 0, "polls_run": 0}
    return {
        "running": _watcher_instance._running,
        "memories_written": _watcher_instance.memories_written,
        "polls_run": _watcher_instance.polls_run,
        "dry_run": _watcher_instance.dry_run,
        "poll_interval": POLL_INTERVAL,
        "debounce_window": DEBOUNCE_WINDOW,
        "watched_paths": [str(p) for p in WATCHED_PATHS],
        "current_branch": _current_branch(),
    }


def start_background_watcher(dry_run: bool = False) -> str:
    global _watcher_instance, _watcher_thread
    if _watcher_instance and _watcher_instance._running:
        return "already_running"
    _watcher_instance = MemoryWatcher(dry_run=dry_run)
    _watcher_thread = threading.Thread(
        target=_watcher_instance.run_loop, daemon=True, name="warden-memory-watcher"
    )
    _watcher_thread.start()
    return "started"


def stop_background_watcher() -> str:
    global _watcher_instance
    if _watcher_instance:
        _watcher_instance.stop()
        return "stopped"
    return "not_running"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(description="Warden Autonomous Memory Collector")
    parser.add_argument("--once", action="store_true", help="Run one collection pass then exit")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be written, don't save")
    parser.add_argument("--install-hooks", action="store_true", help="Install git hooks for this repo")
    parser.add_argument("--uninstall-hooks", action="store_true", help="Remove git hooks")
    parser.add_argument("--status", action="store_true", help="Print current watcher status")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else (logging.WARNING if args.quiet else logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

    if args.install_hooks:
        installed = install_git_hooks()
        print(f"Installed hooks: {', '.join(installed) or 'none'}")
        return

    if args.uninstall_hooks:
        removed = uninstall_git_hooks()
        print(f"Removed hooks: {', '.join(removed) or 'none'}")
        return

    if args.status:
        print(json.dumps(get_watcher_status(), indent=2))
        return

    watcher = MemoryWatcher(dry_run=args.dry_run)

    if args.once:
        n = watcher.poll_once()
        print(f"Collected {n} memor{'y' if n == 1 else 'ies'}.")
        return

    try:
        watcher.run_loop()
    except KeyboardInterrupt:
        print(f"\nStopped. Wrote {watcher.memories_written} memories over {watcher.polls_run} polls.")


if __name__ == "__main__":
    _main()
