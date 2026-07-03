"""Warden Daily Brief — generates a markdown summary from Warden board + memory.

Usage:
    from src.warden.daily_brief import generate_daily_brief
    md = generate_daily_brief()

    # or via REST endpoint (see api.py):
    POST /api/mcharness/warden/notion/daily-brief
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BOARD_ROOT = Path(os.getenv("WARDEN_BOARD_ROOT", os.getenv("MCTABLE_BOARD_ROOT", "~/.local/share/warden/board"))).expanduser()
BRIEF_DIR = Path("~/.local/share/warden-briefs").expanduser()

TASK_STATUSES = ["queued", "claimed", "running", "needs_review", "failed", "completed"]


# ---------------------------------------------------------------------------
# Board helpers
# ---------------------------------------------------------------------------

def _load_tasks(status: str, limit: int = 10) -> List[Dict[str, Any]]:
    d = BOARD_ROOT / "tasks" / status
    if not d.exists():
        return []
    tasks = []
    for f in sorted(d.glob("*.json"), reverse=True)[:limit]:
        try:
            tasks.append(json.loads(f.read_text()))
        except Exception:
            pass
    return tasks


def _load_recent_activity(limit: int = 20) -> List[Dict[str, Any]]:
    activity = []
    act_root = BOARD_ROOT / "activity"
    if not act_root.exists():
        return []
    # last 3 days
    for day_dir in sorted(act_root.iterdir(), reverse=True)[:3]:
        for f in sorted(day_dir.glob("*.jsonl"), reverse=True):
            try:
                for line in f.read_text().splitlines():
                    if line.strip():
                        activity.append(json.loads(line))
                        if len(activity) >= limit:
                            return activity
            except Exception:
                pass
    return activity


def _load_recent_memories(limit: int = 15) -> List[Dict[str, Any]]:
    try:
        from src.warden.workbench import WorkbenchStore
        store = WorkbenchStore()
        mems = store.search_memories("", limit=limit)
        return [m.model_dump(mode="json") for m in mems]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Brief generator
# ---------------------------------------------------------------------------

def generate_daily_brief(date: Optional[str] = None) -> str:
    today = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Gather data
    queued = _load_tasks("queued")
    running = _load_tasks("running") + _load_tasks("claimed")
    needs_review = _load_tasks("needs_review")
    failed = _load_tasks("failed", limit=5)
    completed = _load_tasks("completed", limit=5)
    activity = _load_recent_activity()
    memories = _load_recent_memories()

    # Partition memories by kind
    proofs = [m for m in memories if m.get("kind") == "proof"]
    failures = [m for m in memories if m.get("kind") == "failure"]
    handoffs = [m for m in memories if m.get("kind") == "handoff"]
    decisions = [m for m in memories if m.get("kind") == "decision"]

    def _task_line(t: Dict) -> str:
        return f"- [{t.get('priority', '?')}] **{t.get('title', t.get('task_id', '?'))}** — {t.get('status', '?')}"

    def _mem_line(m: Dict) -> str:
        return f"- **{m.get('title', '?')}** ({m.get('project', 'general')}) — {m.get('summary', '')[:120]}"

    lines: List[str] = [
        f"# Warden Daily Brief — {today}",
        "",
        f"_Generated at {datetime.now(timezone.utc).strftime('%H:%M UTC')}_",
        "",
    ]

    # Top next actions (from queued + needs_review)
    lines += ["## Top Next Actions", ""]
    next_actions = (needs_review + queued)[:5]
    if next_actions:
        for i, t in enumerate(next_actions, 1):
            lines.append(f"{i}. **{t.get('title', t.get('task_id', '?'))}** ({t.get('status', '?')})")
    else:
        lines.append("_No queued tasks._")
    lines.append("")

    # Active agent work
    lines += ["## Active Agent Work", ""]
    if running:
        for t in running:
            lines.append(_task_line(t))
    else:
        lines.append("_No active runs._")
    lines.append("")

    # Proofs
    lines += ["## Proofs", ""]
    if proofs:
        for m in proofs[:5]:
            lines.append(_mem_line(m))
    elif completed:
        for t in completed[:5]:
            lines.append(_task_line(t))
    else:
        lines.append("_No proofs recorded._")
    lines.append("")

    # Failures / blockers
    lines += ["## Failures / Blockers", ""]
    if failures:
        for m in failures[:5]:
            lines.append(_mem_line(m))
    elif failed:
        for t in failed[:5]:
            lines.append(_task_line(t))
    else:
        lines.append("_No failures recorded._")
    lines.append("")

    # Handoffs
    lines += ["## Handoffs", ""]
    if handoffs:
        for m in handoffs[:5]:
            lines.append(_mem_line(m))
    else:
        lines.append("_No open handoffs._")
    lines.append("")

    # Decisions
    lines += ["## Decisions", ""]
    if decisions:
        for m in decisions[:5]:
            lines.append(_mem_line(m))
    else:
        lines.append("_No decisions recorded._")
    lines.append("")

    # Stale tasks (needs_review)
    lines += ["## Stale / Needs Review", ""]
    if needs_review:
        for t in needs_review[:5]:
            lines.append(_task_line(t))
    else:
        lines.append("_Nothing awaiting review._")
    lines.append("")

    # Notion sync candidates
    lines += ["## Notion Sync Candidates", ""]
    candidates = queued[:3]
    if candidates:
        for t in candidates:
            lines.append(f"- {t.get('title', t.get('task_id', '?'))} — `{t.get('task_id', '')}`")
    else:
        lines.append("_No candidates identified._")
    lines.append("")

    # Recommended action
    lines += ["## Recommended Action", ""]
    if needs_review:
        t = needs_review[0]
        lines.append(f"- Review **{t.get('title', t.get('task_id'))}** which is awaiting proof/review.")
    elif queued:
        t = queued[0]
        lines.append(f"- Dispatch **{t.get('title', t.get('task_id'))}** to an agent.")
    elif handoffs:
        m = handoffs[0]
        lines.append(f"- Pick up handoff: **{m.get('title', '?')}**")
    else:
        lines.append("- All clear — no urgent actions.")
    lines.append("")

    return "\n".join(lines)


def save_brief_local(brief_md: str, date: Optional[str] = None) -> Path:
    today = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    path = BRIEF_DIR / f"{today}.md"
    path.write_text(brief_md)
    return path


def generate_and_save(date: Optional[str] = None) -> Dict[str, Any]:
    today = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = generate_daily_brief(date=today)
    path = save_brief_local(md, date=today)
    return {"date": today, "path": str(path), "markdown": md, "ok": True}
