"""Warden Brain MCP Server — universal second-brain interface for any agent.

Run via:  python -m warden.brain_mcp_server
Or:       scripts/warden-brain-mcp
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from src.warden import brain_embed, brain_vector_store, personal_memory
from src.warden.personal_memory import get_workstream, load_profile, update_profile, seed_if_missing

log = logging.getLogger(__name__)

WARDEN_URL = os.getenv("WARDEN_URL", "http://127.0.0.1:8125")
MCTABLE_ROOT = Path(os.getenv("MCHARNESS_DATA_ROOT", "_mctable"))
BOARD_ROOT = Path(os.getenv("WARDEN_BOARD_ROOT", os.getenv("MCTABLE_BOARD_ROOT", "~/.local/share/warden/board"))).expanduser()
SESSION_ID = str(uuid.uuid4())[:8]

from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "warden-brain",
    instructions=(
        "Warden Brain gives you access to Matt McBride's personal second brain. "
        "Start every session by calling warden_me to learn who Matt is and what he's working on. "
        "Use warden_recall to retrieve relevant memories before starting work. "
        "Use warden_remember to save important decisions, proofs, or failures when you're done. "
        "Use warden_workstream to see recent activity across all projects."
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "mcp.mctable.team",
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
        ],
        allowed_origins=[
            "https://mcp.mctable.team",
            "https://www.notion.so",
            "https://notion.so",
        ],
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(tool: str, data: Any) -> str:
    return json.dumps({"schema": "warden.brain.v1", "tool": tool, "ok": True, "data": data}, default=str)


def _err(tool: str, message: str) -> str:
    return json.dumps({"schema": "warden.brain.v1", "tool": tool, "ok": False, "error": message})


def _store():
    from src.warden.workbench import WorkbenchStore
    return WorkbenchStore()


def _brain_ingest():
    from src.marius.brain_ingest import BrainIngest
    return BrainIngest()


def _detect_project(text: str, path: str | None) -> str | None:
    """Auto-detect project from content/path by matching against known active projects."""
    try:
        profile = load_profile()
        projects = profile.get("active_projects", [])
        haystack = ((path or "") + " " + text).lower()
        for p in projects:
            if p.lower() in haystack:
                return p
    except Exception:
        pass
    return None


def _semantic_recall(query: str, limit: int) -> list[dict]:
    """Try semantic search; return [] if Ollama unavailable."""
    embedding = brain_embed.get_embedding(query)
    if not embedding:
        return []
    hits = brain_vector_store.search(embedding, limit=limit)
    if not hits:
        return []
    store = _store()
    all_memories = {m.memory_id: m for m in store.list_memories()}
    results = []
    for hit in hits:
        m = all_memories.get(hit["memory_id"])
        if m and m.status != "forgotten":
            results.append({
                "memory_id": m.memory_id,
                "title": m.title or m.summary[:60],
                "summary": m.summary[:300],
                "kind": m.kind,
                "project": m.project_id or m.scope,
                "tags": m.tags,
                "updated_at": m.updated_at.isoformat(),
                "score": hit["score"],
                "search_mode": "semantic",
            })
    return results


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def warden_health() -> str:
    """Check Warden brain health: API reachability, memory count, semantic index, ingest paths."""
    try:
        import httpx
        try:
            r = httpx.get(f"{WARDEN_URL}/api/mcharness/status", timeout=3.0)
            api_ok = r.status_code < 500
        except Exception:
            api_ok = False

        store = _store()
        memories = store.list_memories()
        mem_count = len(memories)

        semantic_ok = brain_embed.is_available()
        vec_count = brain_vector_store.count()

        obsidian_paths = [
            p for p in [
                Path.home() / "Documents",
                Path.home() / "Obsidian",
                Path("/home/matt/Documents"),
            ]
            if p.exists()
        ]

        return _ok("warden_health", {
            "warden_api_reachable": api_ok,
            "warden_url": WARDEN_URL,
            "memory_available": True,
            "memory_count": mem_count,
            "semantic_index_available": semantic_ok,
            "vector_count": vec_count,
            "embed_model": brain_embed.EMBED_MODEL,
            "ingest_paths_found": [str(p) for p in obsidian_paths],
            "session_id": SESSION_ID,
            "profile_exists": personal_memory.PROFILE_PATH.exists(),
        })
    except Exception as exc:
        return _err("warden_health", str(exc))


@mcp.tool()
def warden_me() -> str:
    """Return Matt's personal profile, current priorities, and active projects.
    Call this first at the start of every session to get full context."""
    try:
        seed_if_missing()
        profile = load_profile()
        workstream = get_workstream(limit=5)
        return _ok("warden_me", {
            "profile": profile,
            "recent_workstream": workstream,
            "session_id": SESSION_ID,
            "tip": "Call warden_workstream for full recent activity, warden_recall for project memories.",
        })
    except Exception as exc:
        return _err("warden_me", str(exc))


@mcp.tool()
def warden_workstream(limit: int = 10, project: str = "") -> str:
    """Return the most recent decisions, proofs, failures, and handoffs across all projects.
    Gives any agent a 'what was I working on' snapshot.

    Args:
        limit: Max items to return (default 10)
        project: Optional project name to filter
    """
    try:
        items = get_workstream(limit=max(1, min(int(limit), 50)), project=project or None)
        return _ok("warden_workstream", {"items": items, "count": len(items), "project_filter": project or None})
    except Exception as exc:
        return _err("warden_workstream", str(exc))


@mcp.tool()
def warden_update_me(field: str, value: str) -> str:
    """Update Matt's personal profile. Agents call this to log new priorities or project changes.

    Args:
        field: One of: priorities, projects, bio, preferences
        value: New value (for lists, use comma-separated string or JSON array string)
    """
    try:
        # Parse list fields
        list_fields = {"priorities", "current_priorities", "projects", "active_projects"}
        if field in list_fields:
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = [v.strip() for v in value.split(",") if v.strip()]
            updated = update_profile(field, parsed)
        else:
            updated = update_profile(field, value)
        return _ok("warden_update_me", {"updated_field": field, "new_value": updated.get(field)})
    except Exception as exc:
        return _err("warden_update_me", str(exc))


@mcp.tool()
def warden_who_is_working() -> str:
    """Return which agent/session last wrote a memory and when. Lets agents detect concurrent activity."""
    try:
        store = _store()
        memories = store.list_memories()
        if not memories:
            return _ok("warden_who_is_working", {"last_activity": None})
        recent = sorted(memories, key=lambda m: m.updated_at, reverse=True)[:1][0]
        return _ok("warden_who_is_working", {
            "last_memory_id": recent.memory_id,
            "last_agent": recent.agent_id,
            "last_project": recent.project_id or recent.scope,
            "last_updated": recent.updated_at.isoformat(),
            "current_session_id": SESSION_ID,
        })
    except Exception as exc:
        return _err("warden_who_is_working", str(exc))


@mcp.tool()
def warden_recall(query: str, project: str = "", limit: int = 10) -> str:
    """Search Warden memory for relevant records. Prefers semantic search; falls back to keyword.

    Args:
        query: What to search for
        project: Optional project scope filter
        limit: Max results (default 10)
    """
    try:
        limit = max(1, min(int(limit), 50))
        scope = project.strip() or None

        # Try semantic first
        results = _semantic_recall(query, limit)
        search_mode = "semantic"

        # Fall back to keyword
        if not results:
            search_mode = "keyword"
            store = _store()
            memories = store.search_memories(query, scope=scope, limit=limit)
            results = [
                {
                    "memory_id": m.memory_id,
                    "title": m.title or m.summary[:60],
                    "summary": m.summary[:300],
                    "kind": m.kind,
                    "project": m.project_id or m.scope,
                    "tags": m.tags,
                    "updated_at": m.updated_at.isoformat(),
                    "search_mode": "keyword",
                }
                for m in memories
            ]

        return _ok("warden_recall", {
            "query": query,
            "project_filter": scope,
            "search_mode": search_mode,
            "count": len(results),
            "results": results,
        })
    except Exception as exc:
        return _err("warden_recall", str(exc))


@mcp.tool()
def warden_context_pack(task: str, project: str = "", limit: int = 8) -> str:
    """Build an agent-ready context pack for a task. Combines Warden memory + brain docs.
    Returns formatted text for prompt injection plus structured metadata.

    Args:
        task: Description of what you're about to work on
        project: Project name (e.g. 'Warden', 'Grademy')
        limit: Max memories to include (default 8)
    """
    try:
        limit = max(1, min(int(limit), 20))
        project = project.strip()

        store = _store()
        pack = store.build_memory_context_pack(
            project_id=project or "warden",
            user_prompt=task,
            max_memories=limit,
        )

        from src.marius.brain_context import build_brain_context_pack
        brain_pack = build_brain_context_pack(task, project=project or None, limit=5)

        combined = pack.get("context", "")
        if brain_pack.get("context_text") and brain_pack["context_text"] != "MARIUS BRAIN CONTEXT: No relevant memory found for this query.":
            combined = combined + "\n\n" + brain_pack["context_text"]

        return _ok("warden_context_pack", {
            "task": task,
            "project": project or None,
            "context": combined,
            "memory_count": pack.get("memory_count", 0),
            "memory_ids": pack.get("memory_ids", []),
            "brain_record_ids": brain_pack.get("record_ids", []),
            "truncated": pack.get("truncated", False),
        })
    except Exception as exc:
        return _err("warden_context_pack", str(exc))


@mcp.tool()
def warden_remember(
    kind: str,
    text: str,
    project: str = "",
    tags: str = "",
    title: str = "",
) -> str:
    """Write a structured memory to Warden. Use this to preserve decisions, proofs, failures, handoffs.

    Args:
        kind: One of: decision, constraint, proof, failure, handoff, note, fact, claim
        text: The memory content
        project: Project name this memory belongs to
        tags: Comma-separated tags
        title: Optional short title (auto-generated from text if omitted)
    """
    try:
        valid_kinds = {
            "decision", "constraint", "proof", "failure", "handoff",
            "user_note", "fact", "claim", "blocked_attempt", "test_result",
            "fragile_file", "acceptance_test", "agent_prompt", "agent_result",
            "repo_context",
        }
        kind = kind.strip().lower()
        if kind == "note":
            kind = "user_note"
        if kind not in valid_kinds:
            kind = "user_note"

        project = project.strip()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        tag_list.append("agent_generated")
        tag_list.append(f"session_{SESSION_ID}")

        if not project:
            project = _detect_project(text, None) or "warden"

        from src.warden.workbench import WorkbenchMemoryRememberRequest
        payload = WorkbenchMemoryRememberRequest(
            scope=project,
            content=text,
            source="warden-brain-mcp",
            title=title.strip() or text[:80],
            tags=tag_list,
            kind=kind,
            project_id=project,
            agent_id="warden-brain-mcp",
            metadata={"agent_generated": True, "session_id": SESSION_ID},
        )
        store = _store()
        memory = store.remember_memory(payload)

        # Embed if Ollama available
        embedding = brain_embed.get_embedding(text)
        if embedding:
            brain_vector_store.upsert(memory.memory_id, embedding, {"kind": kind, "project": project})

        return _ok("warden_remember", {
            "memory_id": memory.memory_id,
            "kind": memory.kind,
            "project": memory.project_id or memory.scope,
            "title": memory.title,
            "embedded": embedding is not None,
        })
    except Exception as exc:
        return _err("warden_remember", str(exc))


@mcp.tool()
def warden_ingest(
    content: str = "",
    path: str = "",
    source_type: str = "manual",
    project: str = "",
    tags: str = "",
) -> str:
    """Ingest content or a file path into the Warden brain.

    Args:
        content: Raw text to ingest (use this OR path)
        path: File path to ingest (must be in an allowed location)
        source_type: One of: obsidian, repo, manual, agent_proof, doc
        project: Project to associate with
        tags: Comma-separated tags
    """
    try:
        if not content and not path:
            return _err("warden_ingest", "Provide content or path")

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        tag_list.append(f"source_{source_type}")
        tag_list.append("agent_generated")

        ingest = _brain_ingest()
        results = []

        if content:
            if not project:
                project = _detect_project(content, path) or "personal"
            title = path.split("/")[-1] if path else f"ingest-{SESSION_ID}"
            result = ingest.add_text(content, title=title, project=project, tags=tag_list)
            if result.get("ok"):
                record_id = result["record"].get("id", "")
                embedding = brain_embed.get_embedding(content[:4000])
                if embedding:
                    brain_vector_store.upsert(record_id, embedding, {"project": project, "source_type": source_type})
                results.append({"id": record_id, "embedded": embedding is not None})

        elif path:
            p = Path(path).expanduser()
            if not p.exists():
                return _err("warden_ingest", f"Path not found: {path}")
            if not project:
                project = _detect_project("", path) or "personal"
            result = ingest.add_file(p, project=project, tags=tag_list)
            if result.get("ok"):
                record_id = result["record"].get("id", "")
                text = result["record"].get("text", "")
                embedding = brain_embed.get_embedding(text[:4000]) if text else None
                if embedding:
                    brain_vector_store.upsert(record_id, embedding, {"project": project, "source_type": source_type})
                results.append({"id": record_id, "embedded": embedding is not None})
            else:
                return _err("warden_ingest", result.get("error", "ingest failed"))

        return _ok("warden_ingest", {
            "ingested": len(results),
            "results": results,
            "project": project,
            "source_type": source_type,
        })
    except Exception as exc:
        return _err("warden_ingest", str(exc))


@mcp.tool()
def warden_search_docs(query: str, project: str = "", limit: int = 5) -> str:
    """Search ingested Obsidian notes, repo files, and brain docs by keyword or semantic similarity.

    Args:
        query: Search query
        project: Optional project filter
        limit: Max results (default 5)
    """
    try:
        limit = max(1, min(int(limit), 20))
        project = project.strip() or None

        # Semantic first
        results = []
        embedding = brain_embed.get_embedding(query)
        if embedding:
            hits = brain_vector_store.search(embedding, limit=limit)
            for h in hits:
                results.append({"id": h["memory_id"], "score": h["score"], "search_mode": "semantic"})

        # Supplement/fallback with keyword search over brain exports
        from src.marius.search_provider import LocalJsonlSearchProvider
        provider = LocalJsonlSearchProvider()
        keyword_results = provider.search(query, project=project, limit=limit)
        seen = {r["id"] for r in results}
        for r in keyword_results:
            if r.get("record_id") not in seen:
                results.append({
                    "id": r.get("record_id"),
                    "title": r.get("title"),
                    "project": r.get("project"),
                    "snippet": r.get("snippet", "")[:300],
                    "score": r.get("score", 0),
                    "search_mode": "keyword",
                })

        return _ok("warden_search_docs", {
            "query": query,
            "project_filter": project,
            "count": len(results),
            "results": results[:limit],
        })
    except Exception as exc:
        return _err("warden_search_docs", str(exc))


@mcp.tool()
def warden_bootstrap(task: str, project: str = "") -> str:
    """THE tool to call first. Returns a single agent-ready startup packet combining:
    - Who Matt is and his current priorities
    - Active projects and preferences
    - Recent workstream (what was worked on last)
    - Relevant memories for this task
    - Relevant docs from the brain
    - Constraints and known failures
    - Recommended next action
    - Proof expectations

    Args:
        task: What you're about to work on (be specific)
        project: Project name (e.g. 'Warden', 'Grademy') — auto-detected if omitted
    """
    try:
        import json as _json

        project = project.strip()

        # 1. Personal profile
        seed_if_missing()
        profile = load_profile()

        # 2. Workstream
        workstream = get_workstream(limit=8, project=project or None)

        # 3. Recall — semantic + keyword
        limit = 10
        recall_results = _semantic_recall(task, limit)
        if not recall_results:
            store = _store()
            scope = project or None
            memories = store.search_memories(task, scope=scope, limit=limit)
            recall_results = [
                {
                    "memory_id": m.memory_id,
                    "title": m.title or m.summary[:60],
                    "summary": m.summary[:300],
                    "kind": m.kind,
                    "project": m.project_id or m.scope,
                    "tags": m.tags,
                    "updated_at": m.updated_at.isoformat(),
                }
                for m in memories
            ]

        # Pull out constraints and failures specifically
        constraints = [r for r in recall_results if r.get("kind") in ("constraint", "blocked_attempt")]
        failures = [r for r in recall_results if r.get("kind") == "failure"]
        other_memories = [r for r in recall_results if r.get("kind") not in ("constraint", "blocked_attempt", "failure")]

        # 4. Context pack (formatted text)
        store = _store()
        pack = store.build_memory_context_pack(
            project_id=project or "warden",
            user_prompt=task,
            max_memories=8,
        )

        # 5. Relevant docs
        from src.marius.search_provider import LocalJsonlSearchProvider
        provider = LocalJsonlSearchProvider()
        doc_results = provider.search(task, project=project or None, limit=5)
        docs = [
            {
                "id": r.get("record_id"),
                "title": r.get("title"),
                "project": r.get("project"),
                "snippet": r.get("snippet", "")[:200],
            }
            for r in doc_results
            if r.get("sensitivity") != "secret_excluded"
        ]

        # 6. Recommended next action heuristic
        if constraints:
            next_action = f"Review {len(constraints)} constraint(s) before starting. Check: " + "; ".join(c.get("title", "") for c in constraints[:2])
        elif failures:
            next_action = f"Note: {len(failures)} prior failure(s) logged for this area. Check before repeating approach."
        elif workstream:
            last = workstream[0]
            next_action = f"Continue from last activity: [{last['kind']}] {last['title']} ({last['project']})"
        else:
            next_action = "No prior context found — this appears to be fresh ground."

        # 7. Proof expectations from profile + memories
        proof_expectations = [
            "Write warden_remember(kind='proof', ...) when task is verified working",
            "Write warden_remember(kind='failure', ...) if approach fails",
            "Write warden_remember(kind='decision', ...) for significant architecture choices",
        ]
        # Add any acceptance_test memories as explicit proof gates
        proof_memories = [m for m in store.list_memories() if m.kind == "acceptance_test" and m.status == "active"]
        if proof_memories and project:
            scoped = [m for m in proof_memories if (m.project_id or m.scope or "").lower() == project.lower()]
            for pm in scoped[:3]:
                proof_expectations.append(f"Acceptance test: {pm.title or pm.summary[:80]}")

        return _ok("warden_bootstrap", {
            "task": task,
            "project": project or None,
            "session_id": SESSION_ID,

            "who_is_matt": {
                "name": profile.get("name"),
                "email": profile.get("email"),
                "bio": profile.get("bio"),
                "active_projects": profile.get("active_projects", []),
                "current_priorities": profile.get("current_priorities", []),
                "preferences": profile.get("preferences", {}),
                "server_context": profile.get("server_context", {}),
            },

            "recent_workstream": workstream,

            "relevant_memories": other_memories,
            "constraints": constraints,
            "prior_failures": failures,

            "context_pack": pack.get("context", ""),
            "context_memory_ids": pack.get("memory_ids", []),

            "relevant_docs": docs,

            "recommended_next_action": next_action,
            "proof_expectations": proof_expectations,

            "tip": (
                "When done: call warden_remember(kind='proof'/'decision'/'failure') to persist your work. "
                "Other agents will see it in their warden_bootstrap on the next session."
            ),
        })
    except Exception as exc:
        return _err("warden_bootstrap", str(exc))


# ---------------------------------------------------------------------------
# Bulletin board / McTable coordination tools
# ---------------------------------------------------------------------------

def _board_path(*parts) -> Path:
    p = BOARD_ROOT.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _task_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower().strip())[:40].strip("-")
    short = str(uuid.uuid4())[:6]
    return f"{slug}-{short}"


@mcp.tool()
def warden_board(project: str = "") -> str:
    """Read the agentic bulletin board — open tasks, active claims, recent handoffs, pulse.
    Call this to see what work is in flight before starting anything.

    Args:
        project: Optional project filter
    """
    try:
        import re as _re
        board = BOARD_ROOT
        if not board.exists():
            return _err("warden_board", f"Board not found at {board}")

        # Open tasks (scan status dirs)
        open_tasks = []
        for status in ("assigned", "claimed", "blocked", "needs_review", "draft"):
            status_dir = board / "tasks" / status
            if status_dir.exists():
                for f in sorted(status_dir.iterdir()):
                    if f.suffix in (".json", ".md", ".yaml"):
                        try:
                            if f.suffix == ".json":
                                data = json.loads(f.read_text())
                            else:
                                data = {"title": f.stem, "raw": f.read_text()[:300]}
                            data["_status"] = status
                            data["_file"] = f.name
                            open_tasks.append(data)
                        except Exception:
                            open_tasks.append({"_status": status, "_file": f.name})

        # Active claims
        claims = []
        claims_dir = board / "claims"
        if claims_dir.exists():
            active_file = claims_dir / "active.jsonl"
            if active_file.exists():
                for line in active_file.read_text().splitlines():
                    line = line.strip()
                    if line:
                        try:
                            claims.append(json.loads(line))
                        except Exception:
                            pass
            for f in claims_dir.glob("*.json"):
                try:
                    claims.append(json.loads(f.read_text()))
                except Exception:
                    pass

        # Recent handoffs
        handoffs = []
        handoffs_dir = board / "handoffs"
        if handoffs_dir.exists():
            files = sorted(handoffs_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
            for f in files[:5]:
                handoffs.append({"file": f.name, "preview": f.read_text()[:300]})

        # PULSE.md snippet
        pulse = ""
        pulse_file = board / "PULSE.md"
        if pulse_file.exists():
            pulse = pulse_file.read_text()[:600]

        return _ok("warden_board", {
            "board_root": str(board),
            "open_tasks": open_tasks[:10],
            "active_claims": claims[-10:],
            "recent_handoffs": handoffs,
            "pulse": pulse,
            "tip": "Use warden_post_task to add work, warden_claim_task to take ownership, warden_handoff to pass to another agent.",
        })
    except Exception as exc:
        return _err("warden_board", str(exc))


@mcp.tool()
def warden_post_task(
    title: str,
    description: str,
    agent: str = "any",
    project: str = "",
    priority: str = "normal",
    files: str = "",
) -> str:
    """Post a task to the agentic bulletin board. Any agent can pick it up.

    Args:
        title: Short task title
        description: Full task description — what needs to be done and why
        agent: Target agent ('claude', 'codex', 'gemini', 'any')
        project: Project this task belongs to
        priority: 'low', 'normal', 'high', 'urgent'
        files: Comma-separated list of relevant files/paths
    """
    try:
        task_id = _task_id(title)
        if not project:
            project = _detect_project(description, None) or "warden"
        file_list = [f.strip() for f in files.split(",") if f.strip()]
        task = {
            "task_id": task_id,
            "title": title,
            "description": description,
            "agent": agent,
            "project": project,
            "priority": priority,
            "files": file_list,
            "status": "assigned" if agent != "any" else "draft",
            "posted_by": f"claude-session-{SESSION_ID}",
            "posted_at": _ts(),
        }
        status_dir = "assigned" if agent != "any" else "draft"
        path = _board_path("tasks", status_dir, f"{task_id}.json")
        path.write_text(json.dumps(task, indent=2))

        # Log to activity
        activity_path = _board_path("activity", datetime.now(timezone.utc).strftime("%Y-%m-%d"), "claude.jsonl")
        with activity_path.open("a") as fp:
            fp.write(json.dumps({"ts": _ts(), "agent": "claude", "action": "POST_TASK", "task": task_id, "note": title}) + "\n")

        return _ok("warden_post_task", {
            "task_id": task_id,
            "file": str(path),
            "status": status_dir,
            "agent": agent,
            "tip": f"Agent '{agent}' can call warden_board to see this task, then warden_claim_task('{task_id}') to take it.",
        })
    except Exception as exc:
        return _err("warden_post_task", str(exc))


@mcp.tool()
def warden_claim_task(task_id: str, agent: str, note: str = "", branch: str = "") -> str:
    """Claim a task from the bulletin board — marks it as yours so no other agent duplicates the work.

    Args:
        task_id: The task ID to claim
        agent: Your agent name ('claude', 'codex', 'gemini', etc.)
        note: What you plan to do
        branch: Git branch you'll work on (if applicable)
    """
    try:
        # Find the task file
        task_file = None
        for status in ("draft", "assigned", "needs_review"):
            candidate = BOARD_ROOT / "tasks" / status / f"{task_id}.json"
            if candidate.exists():
                task_file = candidate
                break

        if not task_file:
            return _err("warden_claim_task", f"Task not found: {task_id}")

        task = json.loads(task_file.read_text())
        task["status"] = "claimed"
        task["claimed_by"] = agent
        task["claimed_at"] = _ts()

        # Move to claimed dir
        claimed_path = _board_path("tasks", "claimed", f"{task_id}.json")
        claimed_path.write_text(json.dumps(task, indent=2))
        task_file.unlink()

        # Write claim record
        claim = {
            "ts": _ts(),
            "agent": agent,
            "action": "CLAIM",
            "task": task_id,
            "branch": branch or f"feat/{task_id}",
            "files": task.get("files", []),
            "note": note or f"Claiming {task_id}",
        }
        claim_path = _board_path("claims", f"{agent}_{task_id}.json")
        claim_path.write_text(json.dumps(claim, indent=2))

        # Append to active.jsonl
        active = _board_path("claims", "active.jsonl")
        with active.open("a") as fp:
            fp.write(json.dumps(claim) + "\n")

        return _ok("warden_claim_task", {
            "task_id": task_id,
            "claimed_by": agent,
            "task_title": task.get("title"),
            "task_description": task.get("description"),
            "files": task.get("files", []),
            "tip": "When done, call warden_handoff to pass to the next agent, or warden_remember(kind='proof') to close it out.",
        })
    except Exception as exc:
        return _err("warden_claim_task", str(exc))


@mcp.tool()
def warden_handoff(
    task_id: str,
    to_agent: str,
    current_state: str,
    next_action: str,
    from_agent: str = "claude",
    files_changed: str = "",
    files_to_inspect: str = "",
    known_blockers: str = "",
    proof_needed: str = "",
    branch: str = "",
) -> str:
    """Write a handoff note — passes a task to another agent with full context so they need zero briefing.

    Args:
        task_id: The task being handed off
        to_agent: Who to hand off to ('codex', 'gemini', 'claude', etc.)
        current_state: What has been done so far
        next_action: Exactly what the next agent should do first
        from_agent: Your agent name
        files_changed: Comma-separated files you changed
        files_to_inspect: Comma-separated files next agent should read
        known_blockers: Any known issues or blockers
        proof_needed: What proof/test would confirm success
        branch: Git branch to continue on
    """
    try:
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        handoff = {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "task": task_id,
            "current_state": current_state,
            "files_changed": [f.strip() for f in files_changed.split(",") if f.strip()],
            "files_to_inspect": [f.strip() for f in files_to_inspect.split(",") if f.strip()],
            "tests_run": [],
            "known_blockers": [b.strip() for b in known_blockers.split(",") if b.strip()],
            "next_action": next_action,
            "proof_needed": proof_needed,
            "branch": branch,
            "commit": "",
            "pr": "",
            "safety_notes": "",
            "metadata": {"session_id": SESSION_ID, "posted_at": _ts()},
        }

        # Write markdown handoff (human-readable)
        md = f"""# Handoff: {task_id}
**From:** {from_agent} → **To:** {to_agent}
**Date:** {now.strftime('%Y-%m-%d %H:%M UTC')}

## Current State
{current_state}

## Next Action
{next_action}

## Files Changed
{chr(10).join('- ' + f for f in handoff['files_changed']) or '(none)'}

## Files to Inspect
{chr(10).join('- ' + f for f in handoff['files_to_inspect']) or '(none)'}

## Known Blockers
{chr(10).join('- ' + b for b in handoff['known_blockers']) or '(none)'}

## Proof Needed
{proof_needed or '(none specified)'}

## Branch
{branch or '(none)'}

---
*To pick this up: call `warden_claim_task('{task_id}', '{to_agent}')` then read the files above.*
"""
        md_path = _board_path("handoffs", f"{date_str}_{task_id}_to_{to_agent}.md")
        md_path.write_text(md)

        # JSON record too
        json_path = _board_path("handoffs", f"{date_str}_{task_id}_to_{to_agent}.json")
        json_path.write_text(json.dumps(handoff, indent=2))

        # Move task to needs_review
        for status in ("claimed", "assigned", "draft"):
            candidate = BOARD_ROOT / "tasks" / status / f"{task_id}.json"
            if candidate.exists():
                task = json.loads(candidate.read_text())
                task["status"] = "needs_review"
                task["handed_to"] = to_agent
                task["handoff_at"] = _ts()
                review_path = _board_path("tasks", "needs_review", f"{task_id}.json")
                review_path.write_text(json.dumps(task, indent=2))
                candidate.unlink()
                break

        # Log activity
        activity_path = _board_path("activity", now.strftime("%Y-%m-%d"), f"{from_agent}.jsonl")
        with activity_path.open("a") as fp:
            fp.write(json.dumps({"ts": _ts(), "agent": from_agent, "action": "HANDOFF", "task": task_id, "to": to_agent}) + "\n")

        # Also save as Warden memory
        try:
            from src.warden.workbench import WorkbenchMemoryRememberRequest, WorkbenchStore
            WorkbenchStore().remember_memory(WorkbenchMemoryRememberRequest(
                scope="warden",
                content=f"Handoff {task_id} from {from_agent} to {to_agent}: {current_state}. Next: {next_action}",
                source="warden-brain-mcp",
                title=f"Handoff {task_id} → {to_agent}",
                tags=["handoff", f"to_{to_agent}", task_id, "agent_generated"],
                kind="handoff",
                agent_id=from_agent,
                metadata={"session_id": SESSION_ID},
            ))
        except Exception:
            pass

        return _ok("warden_handoff", {
            "task_id": task_id,
            "from": from_agent,
            "to": to_agent,
            "handoff_file": str(md_path),
            "next_action": next_action,
            "tip": f"{to_agent} should call warden_board to see this, then warden_claim_task('{task_id}', '{to_agent}').",
        })
    except Exception as exc:
        return _err("warden_handoff", str(exc))


# ---------------------------------------------------------------------------
# WardenAgent + Gateway tools — accessible to any connected agent
# ---------------------------------------------------------------------------

@mcp.tool()
async def warden_agent(message: str, history_json: str = "[]") -> str:
    """Ask the Warden Agent a question — it queries git, GitHub PRs/issues, memory, and web search.

    Use this when you want a synthesised status briefing, e.g.:
    - "where we at with Warden?"
    - "what are the open PRs?"
    - "any recent failures or blockers?"
    - "what decisions have been made about X?"

    Args:
        message: Your question or request.
        history_json: Optional JSON array of {role, content} prior turns for multi-turn use.
    """
    try:
        history = json.loads(history_json) if history_json and history_json.strip() != "[]" else []
        from src.warden.agent import run_agent
        result = await run_agent(message=message, history=history)
        return _ok("warden_agent", {
            "reply": result.reply,
            "tools_used": [t["tool"] for t in result.tools_used],
            "sources": result.sources,
            "model": result.model,
            "provider": result.provider,
            "fallback": result.fallback,
        })
    except Exception as exc:
        return _err("warden_agent", str(exc))


@mcp.tool()
async def warden_ask_marius(message: str, profile: str = "balanced", brain_context: bool = True) -> str:
    """Send a message to Marius (the local AI gateway) and get a response.

    Marius routes to the best available model: local Ollama first, then cloud
    (Groq / Cerebras / OpenRouter) if MARIUS_ALLOW_CLOUD=1 and keys are set.

    Args:
        message: Your question or prompt.
        profile: Model profile — 'fast', 'balanced', 'code', or 'deep'.
        brain_context: Whether to include memory context (default True).
    """
    try:
        from src.marius.provider_gateway import ProviderGateway
        gw = ProviderGateway()
        gw.current_profile = profile
        result = await gw.chat(message, brain_enabled=brain_context)
        return _ok("warden_ask_marius", {
            "response": result.get("response", ""),
            "provider": result.get("provider"),
            "model": result.get("actual"),
            "profile": result.get("profile"),
            "elapsed": result.get("elapsed"),
        })
    except Exception as exc:
        return _err("warden_ask_marius", str(exc))


@mcp.tool()
def warden_memory_context(query: str = "") -> str:
    """Get a live snapshot of Warden memory context: branch, recent commits, shell, board, memories.

    Useful for agents that want to orient themselves quickly without a full agent run.
    """
    try:
        from src.warden.memory_agent import gather_context
        ctx = gather_context(query)
        return _ok("warden_memory_context", {
            "branch": ctx.current_branch,
            "commits": ctx.git_log[:8],
            "shell_commands": ctx.shell_commands[-10:],
            "board_tasks": [
                {"status": t.get("status"), "title": t.get("title")}
                for t in ctx.board_tasks[:8]
            ],
            "recent_memories": [
                {"kind": m.get("kind"), "summary": (m.get("summary") or "")[:160]}
                for m in ctx.recent_memories[:6]
            ],
            "sources": ctx.source_labels(),
            "gathered_at": ctx.gathered_at,
        })
    except Exception as exc:
        return _err("warden_memory_context", str(exc))


# ---------------------------------------------------------------------------
# Captain + Dispatch tools
# ---------------------------------------------------------------------------

@mcp.tool()
def warden_captain_plan(goal: str, repo_id: str = "mcharness-public-export", lane_id: str = "codex_cli") -> str:
    """Create a Captain plan: break a goal into 3–5 bounded, executable steps.

    Args:
        goal: What you want to accomplish.
        repo_id: Target repository ID (default: mcharness-public-export).
        lane_id: Agent lane to use (default: codex_cli).
    """
    try:
        from src.warden.captain_plans import persist_plan
        from src.warden.api import _local_preview_plan

        plan_data = _local_preview_plan(goal=goal, repo_id=repo_id, lane_id=lane_id)
        result = persist_plan(MCTABLE_ROOT, goal=goal, repo_id=repo_id, plan_data=plan_data)
        return _ok("warden_captain_plan", {
            "plan_id": result.get("plan_id"),
            "title": result.get("title"),
            "steps": [
                {"id": s.get("step_id"), "title": s.get("title"), "status": s.get("status")}
                for s in (result.get("steps") or [])
            ],
            "source": result.get("source", "local_preview"),
        })
    except Exception as exc:
        return _err("warden_captain_plan", str(exc))


@mcp.tool()
def warden_captain_recent_plans(limit: int = 5) -> str:
    """List the most recent Captain plans.

    Args:
        limit: How many plans to return (default: 5).
    """
    try:
        from src.warden.captain_plans import list_recent_plans
        plans = list_recent_plans(MCTABLE_ROOT, limit=limit)
        return _ok("warden_captain_recent_plans", {
            "plans": [
                {
                    "plan_id": p.get("plan_id"),
                    "title": p.get("title"),
                    "status": p.get("status"),
                    "current_step_id": p.get("current_step_id"),
                    "step_count": len(p.get("steps") or []),
                }
                for p in plans
            ],
        })
    except Exception as exc:
        return _err("warden_captain_recent_plans", str(exc))


@mcp.tool()
def warden_captain_dispatch_step(plan_id: str, step_id: str) -> str:
    """Dispatch a Captain plan step to the local runner.

    If the runner is unavailable, a blocked_attempt memory is saved honestly.
    Does NOT require runner to be configured — always returns a result.

    Args:
        plan_id: Plan ID to dispatch.
        step_id: Step ID within the plan.
    """
    try:
        from src.warden.captain_plans import get_plan_record, mark_step_dispatched
        from src.warden.run_history import create_run_record
        import uuid

        plan = get_plan_record(MCTABLE_ROOT, plan_id)
        if plan is None:
            return _err("warden_captain_dispatch_step", f"Plan not found: {plan_id}")

        step = next((s for s in (plan.get("steps") or []) if s.get("step_id") == step_id), None)
        if step is None:
            return _err("warden_captain_dispatch_step", f"Step not found: {step_id}")

        repo_id = str(plan.get("repo_id") or "mcharness-public-export")
        step_title = str(step.get("title") or "Captain step")
        prompt = str(step.get("prompt") or "")
        goal = str(plan.get("goal") or plan.get("title") or "")

        # Always use blocked path from MCP — runner may not be in tmux context
        run_id = "mcp-blocked-" + str(uuid.uuid4())[:8]
        create_run_record(
            MCTABLE_ROOT, run_id=run_id, title=f"[mcp-blocked] {step_title}",
            agent_id="codex_cli", agent_adapter="codex_cli", repo_id=repo_id,
            branch=None, prompt=prompt, status="blocked", plan_id=plan_id,
            created_by="mcp_dispatch", service_mode="public",
        )
        from src.warden.api import _write_dispatch_memory
        mem_id = _write_dispatch_memory(
            kind="blocked_attempt", plan_id=plan_id, step_id=step_id,
            step_title=step_title, run_id=run_id, repo_id=repo_id,
            lane_id="codex_cli", goal=goal, reason="mcp_runner_unavailable",
        )
        return _ok("warden_captain_dispatch_step", {
            "ok": True,
            "blocked": True,
            "run_id": run_id,
            "memory_id": mem_id,
            "message": "Runner unavailable from MCP context — blocked attempt saved to Memory",
            "plan_id": plan_id,
            "step_id": step_id,
        })
    except Exception as exc:
        return _err("warden_captain_dispatch_step", str(exc))


@mcp.tool()
def warden_run_get(run_id: str) -> str:
    """Get a run record by ID.

    Args:
        run_id: The run ID to retrieve.
    """
    try:
        from src.warden.run_history import get_run_record
        run = get_run_record(MCTABLE_ROOT, run_id)
        if run is None:
            return _err("warden_run_get", f"Run not found: {run_id}")
        return _ok("warden_run_get", {
            "run_id": run.get("run_id"),
            "title": run.get("title"),
            "status": run.get("status"),
            "agent_id": run.get("agent_id"),
            "repo_id": run.get("repo_id"),
            "plan_id": run.get("plan_id"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "prompt": (run.get("prompt") or "")[:200],
            "transcript_excerpt": (run.get("transcript_excerpt") or "")[:400],
        })
    except Exception as exc:
        return _err("warden_run_get", str(exc))


# ---------------------------------------------------------------------------
# Connector placeholders (wired once connector platform is implemented)
# ---------------------------------------------------------------------------

@mcp.tool()
def warden_connectors_providers() -> str:
    """List available connector providers (Gmail, Outlook, iCloud Mail).

    Returns provider metadata including whether OAuth is configured.
    """
    try:
        from src.warden.connectors.registry import list_providers
        providers = list_providers()
        return _ok("warden_connectors_providers", {"providers": providers})
    except ImportError:
        return _ok("warden_connectors_providers", {
            "providers": [
                {"provider_id": "gmail", "display_name": "Gmail", "auth_type": "oauth2_authorization_code",
                 "configured": False, "enabled": False, "capabilities": ["mail.read"],
                 "risk_level": "read_only", "notes": "Connector platform not yet installed."},
                {"provider_id": "outlook", "display_name": "Outlook / Microsoft 365", "auth_type": "oauth2_authorization_code",
                 "configured": False, "enabled": False, "capabilities": ["mail.read"],
                 "risk_level": "read_only", "notes": "Connector platform not yet installed."},
                {"provider_id": "icloud", "display_name": "iCloud Mail", "auth_type": "app_password",
                 "configured": False, "enabled": False, "capabilities": ["mail.read"],
                 "risk_level": "read_only", "notes": "Connector platform not yet installed."},
            ],
        })
    except Exception as exc:
        return _err("warden_connectors_providers", str(exc))


@mcp.tool()
def warden_connectors_accounts() -> str:
    """List connected user accounts across all providers.

    Tokens and secrets are never returned — only account status metadata.
    """
    try:
        from src.warden.connectors.store import list_accounts
        accounts = list_accounts()
        return _ok("warden_connectors_accounts", {"accounts": accounts})
    except ImportError:
        return _ok("warden_connectors_accounts", {
            "accounts": [],
            "note": "Connector platform not yet installed. No accounts connected.",
        })
    except Exception as exc:
        return _err("warden_connectors_accounts", str(exc))


# ---------------------------------------------------------------------------
# Mail tools
# ---------------------------------------------------------------------------

@mcp.tool()
def warden_mail_accounts_status() -> str:
    """Check status of connected mail accounts (Gmail, iCloud, Outlook).

    Returns a list of connected accounts with provider, email, and status.
    Tokens and passwords are never returned.
    """
    try:
        import urllib.request, json
        url = f"{WARDEN_URL}/api/mcharness/warden/mail/accounts"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        accounts = data.get("accounts", [])
        if not accounts:
            return _ok("warden_mail_accounts_status", {
                "connected": False,
                "note": "No mail accounts connected. Connect Gmail or iCloud in Warden Settings.",
            })
        return _ok("warden_mail_accounts_status", {
            "connected": True,
            "count": len(accounts),
            "accounts": [{"account_id": a.get("account_id"), "provider": a.get("provider"),
                           "display_email": a.get("display_email"), "status": a.get("status")}
                          for a in accounts],
        })
    except Exception as exc:
        return _err("warden_mail_accounts_status", str(exc))


@mcp.tool()
def warden_mail_search(account_id: str, query: str, limit: int = 10) -> str:
    """Search mail in a connected account. Returns message summaries (subject, from, snippet).

    Args:
        account_id: Connected account ID (from warden_mail_accounts_status)
        query: Search terms (e.g. 'from:boss@company.com', 'invoice', 'project update')
        limit: Max results (1-20, default 10)

    Never returns message body, tokens, or passwords.
    Always returns summaries only — use warden_mail_read_message to read full body.
    """
    if not account_id:
        return _err("warden_mail_search", "account_id is required")
    limit = max(1, min(limit, 20))
    try:
        import urllib.request, urllib.parse, json
        params = urllib.parse.urlencode({"account_id": account_id, "q": query, "limit": limit})
        url = f"{WARDEN_URL}/api/mcharness/warden/mail/search?{params}"
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
        return _ok("warden_mail_search", {
            "account_id": account_id,
            "query": query,
            "count": data.get("count", 0),
            "messages": data.get("messages", []),
        })
    except Exception as exc:
        return _err("warden_mail_search", str(exc))


@mcp.tool()
def warden_mail_read_message(account_id: str, message_id: str) -> str:
    """Read a mail message body. Returns plain text body only — no HTML, no tokens.

    Args:
        account_id: Connected account ID
        message_id: Message ID from warden_mail_search results

    Body text is sanitized (no scripts, control chars). HTML body is never returned.
    Ask the user before reading long bodies — prefer search summaries first.
    """
    if not account_id or not message_id:
        return _err("warden_mail_read_message", "account_id and message_id required")
    try:
        import urllib.request, json
        url = f"{WARDEN_URL}/api/mcharness/warden/mail/messages/{urllib.parse.quote(account_id)}/{urllib.parse.quote(message_id)}"
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
        return _ok("warden_mail_read_message", {"message": data.get("message", {})})
    except Exception as exc:
        return _err("warden_mail_read_message", str(exc))


@mcp.tool()
def warden_mail_send_draft(account_id: str, to: str, subject: str, body: str) -> str:
    """[BLOCKED] Send mail — disabled by default. Requires WARDEN_MAIL_ALLOW_SEND=1 and explicit user confirmation.

    This tool is intentionally blocked in v0. To enable:
    1. Set WARDEN_MAIL_ALLOW_SEND=1 in your environment
    2. Restart the Warden API
    3. Still requires explicit user confirmation before each send

    For now: use warden_mail_search and warden_mail_read_message to read mail.
    """
    import os
    if not os.getenv("WARDEN_MAIL_ALLOW_SEND"):
        return _ok("warden_mail_send_draft", {
            "blocked": True,
            "reason": "Mail sending disabled. Set WARDEN_MAIL_ALLOW_SEND=1 and restart Warden to enable.",
        })
    return _err("warden_mail_send_draft", "Send not yet implemented even with WARDEN_MAIL_ALLOW_SEND=1")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _make_auth_middleware(token: str):
    """ASGI middleware that requires Authorization: Bearer <token> on every request."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Allow health check unauthenticated
            if request.url.path == "/health":
                return await call_next(request)
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] != token:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return await call_next(request)

    return BearerAuthMiddleware


def main():
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Warden Brain MCP Server")
    parser.add_argument("--http", action="store_true", help="Run as HTTP server instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8126, help="HTTP port (default: 8126)")
    args = parser.parse_args()

    seed_if_missing()
    logging.basicConfig(level=logging.WARNING)

    if args.http:
        token = os.getenv("WARDEN_BRAIN_TOKEN", "")
        if not token:
            print("ERROR: WARDEN_BRAIN_TOKEN env var required for HTTP mode", flush=True)
            raise SystemExit(1)

        import uvicorn

        # FastMCP's own ASGI app — handles all MCP routing internally
        mcp_app = mcp.streamable_http_app()

        # Pure ASGI auth wrapper — no Starlette nesting that breaks FastMCP routing
        async def app(scope, receive, send):
            if scope["type"] == "lifespan":
                await mcp_app(scope, receive, send)
                return

            if scope["type"] == "http":
                path = scope.get("path", "")

                # Health check — no auth
                if path == "/health":
                    body = json.dumps({"ok": True, "server": "warden-brain", "tools": 18}).encode()
                    await send({"type": "http.response.start", "status": 200,
                                "headers": [[b"content-type", b"application/json"],
                                            [b"content-length", str(len(body)).encode()]]})
                    await send({"type": "http.response.body", "body": body})
                    return

                # All other paths require Bearer token
                headers = {k.lower(): v for k, v in scope.get("headers", [])}
                auth = headers.get(b"authorization", b"").decode()
                if not auth.startswith("Bearer ") or auth[7:] != token:
                    body = b'{"error":"Unauthorized"}'
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [[b"content-type", b"application/json"],
                                            [b"content-length", str(len(body)).encode()]]})
                    await send({"type": "http.response.body", "body": body})
                    return

                # Authenticated — pass to FastMCP
                await mcp_app(scope, receive, send)

        log.warning("Warden Brain MCP HTTP server starting on %s:%s", args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    else:
        asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
