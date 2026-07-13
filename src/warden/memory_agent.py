"""Warden Memory Chat Agent — synthesizes all memory sources into conversational answers."""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
CHAT_MODEL = os.getenv("WARDEN_MEMORY_CHAT_MODEL", "marius-fast:latest")
CANONICAL_REPO = Path(
    os.getenv("WARDEN_CANONICAL_REPO", str(Path(__file__).resolve().parents[2]))
).expanduser()

SYSTEM_PROMPT = """\
You are Warden Memory, a personal AI memory assistant for a software engineer.
Your job is to analyze raw activity data (git commits, file changes, shell commands, \
browser history, task boards, stored memories) and explain what the engineer has been doing \
in clear, human-friendly language.

Rules:
- Be concise but specific. Mention file names, commit messages, and URLs when relevant.
- Use present-perfect tense ("You've been working on...", "You committed...", "You visited...").
- When data is sparse, say so honestly — don't make things up.
- Never expose secrets, tokens, or `.env` values.
- Structure long answers with short paragraphs or bullet points.
- When the user asks a focused question ("What did I commit today?"), answer that first \
  then add relevant context.
"""


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------

@dataclass
class MemoryContext:
    recent_memories: list[dict] = field(default_factory=list)
    latest_dispatch: dict | None = None  # newest blocked_attempt or agent_result
    git_log: list[str] = field(default_factory=list)
    git_diff_stat: str = ""
    shell_commands: list[str] = field(default_factory=list)
    browser_visits: list[dict] = field(default_factory=list)
    board_tasks: list[dict] = field(default_factory=list)
    current_branch: str = ""
    gathered_at: str = ""

    def to_context_block(self) -> str:
        """Render context as a structured text block for the LLM."""
        parts: list[str] = []
        parts.append(f"# Warden Memory Context — {self.gathered_at}")

        if self.current_branch:
            parts.append(f"\n## Git State\nBranch: {self.current_branch}")
        if self.git_log:
            parts.append("Recent commits:\n" + "\n".join(f"  • {c}" for c in self.git_log[:10]))
        if self.git_diff_stat:
            parts.append(f"Working tree diff:\n{self.git_diff_stat[:800]}")

        if self.shell_commands:
            parts.append("\n## Shell Commands (recent, relevant)")
            parts.append("\n".join(f"  $ {c}" for c in self.shell_commands[-20:]))

        if self.browser_visits:
            parts.append("\n## Browser Activity (work URLs)")
            for v in self.browser_visits[-15:]:
                parts.append(f"  [{v.get('visited_at','?')}] {v.get('title','?')} — {v.get('url','')}")

        if self.board_tasks:
            parts.append("\n## Task Board")
            for t in self.board_tasks[:10]:
                status = t.get("status", "?")
                title = t.get("title", "Untitled")
                agent = t.get("agent", "")
                parts.append(f"  [{status}] {title}" + (f" ({agent})" if agent else ""))

        if self.latest_dispatch:
            d = self.latest_dispatch
            meta = d.get("metadata") or {}
            parts.append("\n## Latest Dispatch Run")
            parts.append(f"  kind: {d.get('kind','?')}")
            parts.append(f"  summary: {d.get('summary','')[:120]}")
            parts.append(f"  memory_id: {d.get('memory_id','?')}")
            parts.append(f"  source: {d.get('source','?')}")
            if meta.get("run_id"):
                parts.append(f"  run_id: {meta['run_id']}")
            if meta.get("plan_id"):
                parts.append(f"  plan_id: {meta['plan_id']}")
            if meta.get("step_id"):
                parts.append(f"  step_id: {meta['step_id']}")
            if meta.get("step_title"):
                parts.append(f"  step_title: {meta['step_title'][:80]}")
            if meta.get("lane_id"):
                parts.append(f"  lane: {meta['lane_id']}")
            if meta.get("reason"):
                parts.append(f"  reason: {meta['reason']}")
            if meta.get("goal"):
                parts.append(f"  goal: {meta['goal'][:100]}")
            parts.append(f"  timestamp: {d.get('created_at','?')}")

        if self.recent_memories:
            parts.append("\n## Stored Memories (most recent first)")
            for m in self.recent_memories[:12]:
                kind = m.get("kind", "context")
                summary = m.get("summary", "")[:200]
                source = m.get("source", "")
                line = f"  [{kind}] {summary}" + (f" — {source}" if source else "")
                # For captain plan memories, surface structured metadata inline
                meta = m.get("metadata") or {}
                if source == "captain" and isinstance(meta, dict):
                    plan_id = meta.get("plan_id", "")
                    goal = meta.get("goal", "")
                    src = meta.get("source", "")
                    steps = meta.get("step_count", "")
                    extras = []
                    if plan_id:
                        extras.append(f"plan_id={plan_id}")
                    if goal:
                        extras.append(f"goal={goal[:60]}")
                    if src:
                        extras.append(f"source={src}")
                    if steps:
                        extras.append(f"steps={steps}")
                    if extras:
                        line += f" [{', '.join(extras)}]"
                parts.append(line)

        return "\n".join(parts)

    def source_labels(self) -> list[str]:
        labels = []
        if self.git_log or self.current_branch:
            labels.append("git")
        if self.shell_commands:
            labels.append("shell")
        if self.browser_visits:
            labels.append("chrome")
        if self.board_tasks:
            labels.append("board")
        if self.recent_memories:
            labels.append("memories")
        return labels


def _git_log(repo: Path, n: int = 15) -> tuple[list[str], str]:
    """Returns (commits, branch)."""
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, stderr=subprocess.DEVNULL
        ).decode().strip()
        log_lines = subprocess.check_output(
            ["git", "log", f"-{n}", "--oneline", "--no-decorate"],
            cwd=repo, stderr=subprocess.DEVNULL,
        ).decode().strip().splitlines()
        return log_lines, branch
    except Exception:
        return [], ""


def _git_diff_stat(repo: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "diff", "--stat", "HEAD"], cwd=repo, stderr=subprocess.DEVNULL
        ).decode().strip()[:1000]
    except Exception:
        return ""


def _recent_shell(limit: int = 30) -> list[str]:
    """Pull recent relevant commands from shell history."""
    try:
        from .memory_watcher import ShellHistoryCollector, SHELL_HISTORY_PATHS  # type: ignore
        collector = ShellHistoryCollector()
        # Reset offsets to 0 to read more history
        for p in SHELL_HISTORY_PATHS:
            ps = str(p)
            if p.exists():
                # Read last `limit*4` bytes to get recent commands
                size = p.stat().st_size
                offset = max(0, size - limit * 80)
                collector._offsets[ps] = offset
        return collector.poll()[-limit:]
    except Exception:
        return []


def _recent_browser(limit: int = 20) -> list[dict]:
    try:
        from .memory_watcher import ChromeCollector  # type: ignore
        collector = ChromeCollector()
        collector._last_visit_time = int((time.time() - 3600 * 24) * 1_000_000)  # last 24h
        return collector.poll()[-limit:]
    except Exception:
        return []


def _board_tasks(limit: int = 15) -> list[dict]:
    board_root = Path(
        os.getenv("WARDEN_BOARD_ROOT", os.getenv("MCTABLE_BOARD_ROOT", "~/.local/share/warden/board"))
    ).expanduser()
    tasks = []
    for status_dir in board_root.glob("tasks/*/"):
        for task_file in sorted(status_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]:
            try:
                data = json.loads(task_file.read_text())
                data.setdefault("status", status_dir.name)
                tasks.append(data)
            except Exception:
                pass
    tasks.sort(key=lambda t: t.get("updated_at", t.get("created_at", "")), reverse=True)
    return tasks[:limit]


def _recent_memories(query: str = "", limit: int = 12) -> list[dict]:
    try:
        from .workbench import WorkbenchStore  # type: ignore
        store = WorkbenchStore()
        # Pass empty string when no query — returns most-recent-first without term filtering
        mems = store.search_memories(query=query or "", limit=limit)
        return [m if isinstance(m, dict) else m.__dict__ for m in mems]
    except Exception:
        return []


def _latest_dispatch() -> dict | None:
    """Return the single most recent blocked_attempt/agent_result/proof memory."""
    try:
        from .workbench import WorkbenchStore  # type: ignore
        store = WorkbenchStore()
        # list_memories is already sorted newest-first
        for m in store.list_memories():
            if m.kind in ("blocked_attempt", "agent_result", "proof") and \
               m.source in ("captain_dispatch", "agent_dispatcher", "captain"):
                return m if isinstance(m, dict) else m.__dict__
    except Exception:
        pass
    return None


def gather_context(query: str = "") -> MemoryContext:
    """Pull data from all sources in parallel-ish (sequential, fast enough)."""
    from datetime import datetime, timezone
    git_log, branch = _git_log(CANONICAL_REPO)
    diff_stat = _git_diff_stat(CANONICAL_REPO)
    ctx = MemoryContext(
        recent_memories=_recent_memories(query),
        latest_dispatch=_latest_dispatch(),
        git_log=git_log,
        git_diff_stat=diff_stat,
        shell_commands=_recent_shell(),
        browser_visits=_recent_browser(),
        board_tasks=_board_tasks(),
        current_branch=branch,
        gathered_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    return ctx


# ---------------------------------------------------------------------------
# LLM call via Ollama
# ---------------------------------------------------------------------------

def _ollama_chat(messages: list[dict], model: str = CHAT_MODEL, timeout: float = 60.0) -> str:
    """Call Ollama chat API. Returns assistant text or raises."""
    import urllib.request
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 1024},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"].strip()


def _fallback_structured_answer(question: str, ctx: MemoryContext) -> str:
    """Return a structured plain-text answer without LLM — used when Ollama is down."""
    q_lower = question.lower()
    is_run_query = any(t in q_lower for t in ("agent run", "last run", "dispatch", "did the last", "proof", "blocked"))

    lines = [f"Warden Memory Snapshot — {ctx.gathered_at}", ""]

    # Surface latest dispatch run first if the question is about agent runs
    if ctx.latest_dispatch and is_run_query:
        d = ctx.latest_dispatch
        meta = d.get("metadata") or {}
        kind = d.get("kind", "?")
        lines.append("**Latest Agent Run:**")
        lines.append(f"  Status: {kind}")
        lines.append(f"  {d.get('summary','')[:120]}")
        if meta.get("run_id"):
            lines.append(f"  Run ID: {meta['run_id']}")
        if meta.get("plan_id"):
            lines.append(f"  Plan: {meta['plan_id']}")
        if meta.get("step_title"):
            lines.append(f"  Step: {meta['step_title'][:80]}")
        if meta.get("lane_id"):
            lines.append(f"  Lane: {meta['lane_id']}")
        if meta.get("reason"):
            lines.append(f"  Reason: {meta['reason']}")
        if meta.get("goal"):
            lines.append(f"  Goal: {meta['goal'][:100]}")
        lines.append(f"  Memory ID: {d.get('memory_id','?')}")
        lines.append("")

    if ctx.current_branch:
        lines.append(f"**Branch:** `{ctx.current_branch}`")
    if ctx.git_log:
        lines.append("\n**Recent commits:**")
        for c in ctx.git_log[:5]:
            lines.append(f"  • {c}")

    if ctx.shell_commands:
        lines.append("\n**Recent shell activity:**")
        for c in ctx.shell_commands[-8:]:
            lines.append(f"  $ {c}")

    if ctx.browser_visits:
        lines.append("\n**Recent browser visits:**")
        for v in ctx.browser_visits[-5:]:
            lines.append(f"  [{v.get('visited_at','?')}] {v.get('title','?')}")

    if ctx.board_tasks:
        lines.append("\n**Active tasks:**")
        for t in ctx.board_tasks[:5]:
            lines.append(f"  [{t.get('status','?')}] {t.get('title','Untitled')}")

    if ctx.recent_memories:
        lines.append("\n**Stored memories:**")
        for m in ctx.recent_memories[:4]:
            lines.append(f"  [{m.get('kind','?')}] {m.get('summary','')[:120]}")

    if not any([ctx.git_log, ctx.shell_commands, ctx.browser_visits, ctx.board_tasks, ctx.recent_memories, ctx.latest_dispatch]):
        lines.append("No activity data collected yet. Start the memory watcher to begin capturing context.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public chat API
# ---------------------------------------------------------------------------

def _build_memory_trace(ctx: "MemoryContext", sources: list[str], fallback: bool,
                         model_used: str) -> dict:
    """Build a Marius-compatible trace dict for a Memory Agent response."""
    import uuid as _uuid
    from datetime import datetime, timezone as _tz
    now = datetime.now(_tz.utc).isoformat()
    steps = []

    if fallback:
        steps.append({"type": "note", "label": "Fallback mode — Ollama unavailable",
                       "status": "blocked", "detail": "Using static context only.", "ref": "",
                       "visibility": "user", "timestamp": now})

    # Context loaded
    ctx_parts = []
    if ctx.current_branch:
        ctx_parts.append(f"branch: {ctx.current_branch}")
    if ctx.git_log:
        ctx_parts.append(f"{len(ctx.git_log)} recent commits")
    if ctx.shell_commands:
        ctx_parts.append(f"{len(ctx.shell_commands)} shell commands")
    if ctx.browser_visits:
        ctx_parts.append(f"{len(ctx.browser_visits)} browser visits")
    if ctx_parts:
        steps.append({"type": "context_read", "label": "Context loaded",
                       "status": "ok", "detail": ", ".join(ctx_parts), "ref": "",
                       "visibility": "user", "timestamp": now})

    # Memories read
    if ctx.recent_memories:
        steps.append({"type": "memory_read", "label": f"{len(ctx.recent_memories)} memories loaded",
                       "status": "ok", "detail": ", ".join(sources), "ref": "",
                       "visibility": "user", "timestamp": now})
    else:
        steps.append({"type": "memory_read", "label": "Memory read",
                       "status": "skipped", "detail": "No recent memories found.", "ref": "",
                       "visibility": "user", "timestamp": now})

    # Latest dispatch
    if ctx.latest_dispatch:
        steps.append({"type": "proof", "label": "Latest dispatch loaded",
                       "status": "ok",
                       "detail": f"{ctx.latest_dispatch.get('kind', 'blocked_attempt')} — {ctx.latest_dispatch.get('summary', '')[:80]}",
                       "ref": ctx.latest_dispatch.get("memory_id", ""),
                       "visibility": "user", "timestamp": now})

    # Routing
    steps.append({"type": "note", "label": f"Model: {model_used}",
                   "status": "ok", "detail": "Warden Memory Agent", "ref": "",
                   "visibility": "debug", "timestamp": now})

    return {
        "trace_id": "mem-trace-" + _uuid.uuid4().hex[:10],
        "agent": "Warden Memory Agent",
        "steps": steps,
    }


@dataclass
class ChatResponse:
    reply: str
    sources: list[str]
    model_used: str
    context_snapshot: dict
    fallback: bool = False
    trace: dict | None = None


def chat(
    message: str,
    history: list[dict] | None = None,
    model: str | None = None,
) -> ChatResponse:
    """
    Core chat function. Gathers context, calls LLM, returns structured response.

    history: list of {role: "user"|"assistant", content: str}
    """
    ctx = gather_context(query=message)
    context_block = ctx.to_context_block()
    sources = ctx.source_labels()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context_block},
    ]
    for h in (history or []):
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    used_model = model or CHAT_MODEL
    fallback = False
    try:
        reply = _ollama_chat(messages, model=used_model)
    except Exception as e:
        reply = _fallback_structured_answer(message, ctx)
        fallback = True
        used_model = "fallback"

    trace = _build_memory_trace(ctx, sources, fallback, used_model)
    return ChatResponse(
        reply=reply,
        sources=sources,
        model_used=used_model,
        context_snapshot={
            "branch": ctx.current_branch,
            "commits": len(ctx.git_log),
            "shell_commands": len(ctx.shell_commands),
            "browser_visits": len(ctx.browser_visits),
            "board_tasks": len(ctx.board_tasks),
            "memories": len(ctx.recent_memories),
            "latest_dispatch": ctx.latest_dispatch.get("memory_id") if ctx.latest_dispatch else None,
            "gathered_at": ctx.gathered_at,
        },
        fallback=fallback,
        trace=trace,
    )
