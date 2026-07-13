"""Warden Brain MCP Server — universal second-brain interface for any agent.

Run via:  python -m warden.brain_mcp_server
Or:       scripts/warden-brain-mcp
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from src.marius.tools import get_git_status, get_service_status
from src.warden import brain_embed, brain_vector_store, mcp_hub, personal_memory
from src.warden.personal_memory import get_workstream, load_profile, update_profile, seed_if_missing

log = logging.getLogger(__name__)

WARDEN_URL = os.getenv("WARDEN_URL", "http://127.0.0.1:8125")
from src.warden.paths import data_root as _warden_data_root
MCTABLE_ROOT = _warden_data_root()
BOARD_ROOT = Path(os.getenv("WARDEN_BOARD_ROOT", os.getenv("MCTABLE_BOARD_ROOT", "~/.local/share/warden/board"))).expanduser()
SESSION_ID = str(uuid.uuid4())[:8]

# Server-status tools: read-only, no arbitrary shell exec.
WORKSPACES_ROOT = Path(os.getenv("WARDEN_WORKSPACES_ROOT", str(Path.home() / "workspaces")))
DEFAULT_SERVICE_ALLOWLIST = [
    "mcharness-cockpit",
    "mcharness-cockpit-private",
    "warden-brain-ingest-obsidian.timer",
    "warden-brain-ingest-warden.service",
]
REPO_CATALOG_MAX_DEPTH = 4

from mcp.server.transport_security import TransportSecuritySettings
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

from .mcp_oauth import OAuthProvider

_OAUTH_ISSUER_URL = os.getenv("MCP_OAUTH_ISSUER_URL", "https://mcp.mctable.online")

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
            "mcp.mctable.online",
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
        ],
        allowed_origins=[
            "https://mcp.mctable.team",
            "https://mcp.mctable.online",
            "https://www.notion.so",
            "https://notion.so",
        ],
    ),
    auth_server_provider=OAuthProvider(),
    auth=AuthSettings(
        issuer_url=_OAUTH_ISSUER_URL,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=["mcp"], default_scopes=["mcp"]
        ),
        revocation_options=RevocationOptions(enabled=True),
        resource_server_url=_OAUTH_ISSUER_URL,
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
            r = httpx.get(f"{WARDEN_URL}/api/mcharness/health", timeout=3.0)
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
def warden_mcp_hub_status() -> str:
    """Report the MCP Hub's status: whether the McTable gateway was reachable
    at boot, how many of its tools got proxied into Warden, and any
    name collisions that were skipped. Useful over stdio transport where the
    /health HTTP endpoint isn't reachable."""
    try:
        hs = mcp_hub.hub_status()
        return _ok("warden_mcp_hub_status", {
            "enabled": hs.enabled,
            "reachable_at_boot": hs.reachable_at_boot,
            "last_discovery_at": hs.last_discovery_at,
            "last_error": hs.last_error,
            "hub_tool_count": hs.hub_tool_count,
            "native_tool_count": hs.native_tool_count,
            "hub_tool_names": hs.hub_tool_names,
            "skipped_collisions": hs.skipped_collisions,
        })
    except Exception as exc:
        return _err("warden_mcp_hub_status", str(exc))


def _read_meminfo() -> dict[str, Any]:
    """Parse /proc/meminfo (stdlib only, no psutil)."""
    info: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                value = rest.strip().split()[0]
                info[key] = int(value)  # kB
    except Exception:
        return {"available": False}
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    used = total - available
    return {
        "available": True,
        "total_kb": total,
        "available_kb": available,
        "used_kb": used,
        "used_percent": round(used / total * 100, 1) if total else None,
    }


@mcp.tool()
def warden_server_status() -> str:
    """Read-only snapshot of the host: load average, disk usage, memory, and
    status for an allowlisted set of Warden-related systemd services.
    No arbitrary shell execution; secrets are never included in this output."""
    try:
        disk = shutil.disk_usage("/")
        load = os.getloadavg() if hasattr(os, "getloadavg") else None
        return _ok("warden_server_status", {
            "load_average": {"1m": load[0], "5m": load[1], "15m": load[2]} if load else None,
            "disk": {
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
                "used_percent": round(disk.used / disk.total * 100, 1) if disk.total else None,
            },
            "memory": _read_meminfo(),
            "services": get_service_status(),
            "git_status": get_git_status(),
        })
    except Exception as exc:
        return _err("warden_server_status", str(exc))


@mcp.tool()
def warden_service_health(services: str = "") -> str:
    """Check systemd --user service/timer status for an allowlisted set of
    Warden-related units. No arbitrary service names are executed beyond the
    allowlist.

    Args:
        services: Optional comma-separated subset of the allowlist to check.
            Unknown names are ignored. Defaults to the full allowlist.
    """
    try:
        requested = [s.strip() for s in services.split(",") if s.strip()] if services else None
        names = [s for s in requested if s in DEFAULT_SERVICE_ALLOWLIST] if requested else DEFAULT_SERVICE_ALLOWLIST
        results = []
        for name in names:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", name],
                capture_output=True, text=True, check=False,
            )
            results.append({"service": name, "status": proc.stdout.strip() or "unknown"})
        return _ok("warden_service_health", {"services": results, "allowlist": DEFAULT_SERVICE_ALLOWLIST})
    except Exception as exc:
        return _err("warden_service_health", str(exc))


@mcp.tool()
def warden_repo_catalog(root: str = "") -> str:
    """List git repositories under the Warden workspaces root, with current
    branch and a dirty/clean flag for each. Read-only; runs git only against
    discovered repo paths, never against arbitrary user input.

    Args:
        root: Optional override of the workspaces root to scan (must exist).
            Defaults to WARDEN_WORKSPACES_ROOT (~/workspaces).
    """
    try:
        base = Path(root).expanduser() if root else WORKSPACES_ROOT
        if not base.is_dir():
            return _err("warden_repo_catalog", f"root does not exist or is not a directory: {base}")

        repos: list[dict[str, Any]] = []

        def scan(dir_path: Path, depth: int) -> None:
            if depth > REPO_CATALOG_MAX_DEPTH:
                return
            if (dir_path / ".git").exists():
                branch_proc = subprocess.run(
                    ["git", "-C", str(dir_path), "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, check=False,
                )
                status_proc = subprocess.run(
                    ["git", "-C", str(dir_path), "status", "--short"],
                    capture_output=True, text=True, check=False,
                )
                repos.append({
                    "path": str(dir_path),
                    "branch": branch_proc.stdout.strip() or "unknown",
                    "dirty": bool(status_proc.stdout.strip()),
                })
                return  # don't descend into a repo's internals looking for nested repos
            try:
                children = [p for p in dir_path.iterdir() if p.is_dir() and not p.name.startswith(".")]
            except (PermissionError, OSError):
                return
            for child in children:
                scan(child, depth + 1)

        scan(base, 0)
        return _ok("warden_repo_catalog", {"root": str(base), "repos": repos, "count": len(repos)})
    except Exception as exc:
        return _err("warden_repo_catalog", str(exc))


@mcp.tool()
def warden_listening_ports() -> str:
    """List listening TCP ports on the host via a fixed, non-interpolated
    `ss -tln` command. No arbitrary shell execution; no user input reaches
    the command line."""
    try:
        proc = subprocess.run(
            ["ss", "-tln"],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            return _err("warden_listening_ports", proc.stderr.strip() or "ss command failed")

        rows = []
        lines = proc.stdout.strip().splitlines()
        for line in lines[1:]:  # skip header
            parts = line.split()
            if len(parts) < 5:
                continue
            local_addr = parts[3]
            addr, _, port = local_addr.rpartition(":")
            rows.append({
                "proto": parts[0],
                "state": parts[1],
                "local_address": addr or local_addr,
                "port": port or None,
            })
        return _ok("warden_listening_ports", {"ports": rows, "count": len(rows)})
    except FileNotFoundError:
        return _err("warden_listening_ports", "ss command not available on this host")
    except Exception as exc:
        return _err("warden_listening_ports", str(exc))


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

        payload = {
            "query": query,
            "project_filter": scope,
            "search_mode": search_mode,
            "count": len(results),
            "results": results,
        }
        if search_mode == "keyword" and not brain_embed.is_available():
            payload["note"] = (
                f"Semantic search is off — no embedding backend at {brain_embed.OLLAMA_URL}. "
                f"Results are keyword-only. Start Ollama and pull '{brain_embed.EMBED_MODEL}' "
                "to enable semantic recall."
            )
        return _ok("warden_recall", payload)
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


def _within_vault(p: Path) -> bool:
    from src.warden.brain.vault import get_vault_path
    try:
        p.resolve().relative_to(get_vault_path().resolve())
        return True
    except ValueError:
        return False


def _obsidian_vault_root() -> Path:
    raw = os.getenv("WARDEN_OBSIDIAN_VAULT_PATH", "~/Documents/Obsidian Vault")
    return Path(raw).expanduser()


def _obsidian_import_allowed(p: Path) -> bool:
    try:
        p.resolve().relative_to(_obsidian_vault_root().resolve())
        return True
    except ValueError:
        return False


@mcp.tool()
def warden_ingest(
    content: str = "",
    path: str = "",
    source_type: str = "manual",
    project: str = "",
    tags: str = "",
) -> str:
    """Ingest content or a file path into the Warden brain vault + search index.

    Writes through the same vault and SQLite FTS index used by brain_search /
    brain_reindex / brain_list_sources, so a successful response means the
    content is actually searchable — not just recorded somewhere else.
    Duplicate content (by normalized hash) is detected and reported instead
    of creating another copy.

    Args:
        content: Raw text to ingest (use this OR path)
        path: File path to ingest — must be inside the Warden Brain vault, or
            inside the configured Obsidian vault when source_type="obsidian"
        source_type: One of: obsidian, repo, manual, agent_proof, doc
        project: Project to associate with
        tags: Comma-separated tags
    """
    try:
        if not content and not path:
            return _err("warden_ingest", "Provide content or path")

        from src.warden.brain.ingest import ingest_generic, GENERIC_SOURCE_TYPES

        if source_type not in GENERIC_SOURCE_TYPES:
            return _err(
                "warden_ingest",
                f"Unknown source_type {source_type!r}; must be one of {sorted(GENERIC_SOURCE_TYPES)}",
            )

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]

        if path:
            p = Path(path).expanduser()
            allowed = _within_vault(p) or (source_type == "obsidian" and _obsidian_import_allowed(p))
            if not allowed:
                return _err(
                    "warden_ingest",
                    f"Path not allowed: {path}. Must be inside the Warden Brain vault, "
                    f"or inside the Obsidian vault with source_type='obsidian'.",
                )
            if not p.exists():
                return _err("warden_ingest", f"Path not found: {path}")
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return _err("warden_ingest", f"Could not read {path}: {exc}")
            title = p.stem
        else:
            text = content
            title = f"ingest-{SESSION_ID}"

        if not project:
            project = _detect_project(text, path) or "personal"

        result = ingest_generic(
            text=text,
            title=title,
            source_type=source_type,
            project=project,
            tags=tag_list,
        )
        if not result.get("ok"):
            return _err("warden_ingest", result.get("error", "ingest failed"))

        if result.get("duplicate"):
            return _ok("warden_ingest", {
                "ingested": 0,
                "duplicate": True,
                "duplicate_of": result.get("duplicate_of"),
                "project": project,
                "source_type": source_type,
            })

        embedding = brain_embed.get_embedding(text[:4000])
        if embedding:
            brain_vector_store.upsert(result["source_id"], embedding, {"project": project, "source_type": source_type})

        return _ok("warden_ingest", {
            "ingested": 1,
            "results": [{"id": result["source_id"], "path": result["path"], "embedded": embedding is not None}],
            "project": project,
            "source_type": source_type,
        })
    except Exception as exc:
        return _err("warden_ingest", str(exc))


@mcp.tool()
def brain_import_obsidian(source_path: str = "") -> str:
    """Import Markdown notes from an external Obsidian vault into Warden Brain.

    Read-only against the source vault — never writes back to it. Each
    imported note is tagged 'obsidian-vault', deduped by content hash, and
    becomes searchable via brain_search after this call.

    Args:
        source_path: Obsidian vault root. Defaults to WARDEN_OBSIDIAN_VAULT_PATH
            (or ~/Documents/Obsidian Vault if unset).
    """
    try:
        from src.warden.brain.ingest import import_obsidian_vault
        src = source_path.strip() or str(_obsidian_vault_root())
        result = import_obsidian_vault(src)
        if not result.get("ok"):
            return _err("brain_import_obsidian", result.get("error", "import failed"))
        return _ok("brain_import_obsidian", result)
    except Exception as exc:
        return _err("brain_import_obsidian", str(exc))


@mcp.tool()
def brain_promote_inbox(dry_run: bool = False) -> str:
    """Dedupe and file 00-inbox notes into project/people/research/etc folders.

    Deterministic, tag-based routing — no LLM. Duplicates (by content hash)
    are archived under 90-archive/duplicates instead of left cluttering the
    inbox. Notes with no matching tag stay in 00-inbox and are reported as
    unclassified rather than guessed at.

    Args:
        dry_run: If true, report what would move without moving anything.
    """
    try:
        from src.warden.brain.promote import promote_inbox
        result = promote_inbox(dry_run=dry_run)
        return _ok("brain_promote_inbox", result)
    except Exception as exc:
        return _err("brain_promote_inbox", str(exc))


@mcp.tool()
def brain_distill_wiki(
    title: str,
    definition: str,
    principles: str = "",
    examples: str = "",
    tags: str = "",
    links: str = "",
    source_path: str = "",
) -> str:
    """Write (or update) a wiki page — the curated, human/agent-synthesized
    layer of Warden Brain, distinct from raw ingested sources.

    This is the Karpathy-style raw -> wiki -> schema pattern: read a source
    fully, synthesize what it actually means, then call this tool with the
    result. Re-calling with the same title updates that page in place
    instead of creating a duplicate. Keep 'links' tight — only include a
    title if understanding one page would meaningfully change how you see
    the other (see brain_search or the Brain Graph for what already exists
    to link against).

    Args:
        title: Short, specific concept title for the page.
        definition: One to three sentences defining the concept.
        principles: Newline- or comma-separated key takeaways.
        examples: Newline- or comma-separated concrete examples (optional).
        tags: Comma-separated lowercase kebab-case topic tags.
        links: Comma-separated titles of existing wiki pages this relates to.
        source_path: Vault-relative path of the raw source this was distilled from.
    """
    try:
        from src.warden.brain.wiki import distill_note

        def _split(raw: str) -> list[str]:
            parts = re.split(r"[\n,]+", raw or "")
            return [p.strip() for p in parts if p.strip()]

        result = distill_note(
            title=title,
            definition=definition,
            principles=_split(principles),
            examples=_split(examples),
            tags=_split(tags),
            links=_split(links),
            source_path=source_path.strip() or None,
        )
        return _ok("brain_distill_wiki", result)
    except ValueError as exc:
        return _err("brain_distill_wiki", str(exc))
    except Exception as exc:
        return _err("brain_distill_wiki", str(exc))


@mcp.tool()
async def brain_curate_wiki(limit: int = 5, dry_run: bool = False) -> str:
    """Run automatic wiki curation via the Marius model gateway (Ollama-first,
    OpenRouter fallback — same routing as every other agent call).

    Finds promoted vault notes that don't have a wiki page yet, distills
    each one (title, definition, principles, examples, tight links) through
    the gateway, and writes the results — one source at a time, so later
    sources in the same run can link to pages distilled earlier in it.

    Args:
        limit: Max sources to distill this call (default 5, keep small).
        dry_run: If true, report what would be distilled without calling the model.
    """
    try:
        from src.warden.brain.curator import curate_vault
        result = await curate_vault(limit=limit, dry_run=dry_run)
        return _ok("brain_curate_wiki", result)
    except Exception as exc:
        return _err("brain_curate_wiki", str(exc))


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
async def warden_captain_plan(goal: str, repo_id: str = "mcharness-public-export", lane_id: str = "codex_cli") -> str:
    """Create a Captain plan: break a goal into 3–5 bounded, executable steps.

    Uses the same real planner as the web UI (OpenRouter key if configured,
    else the local Marius gateway, else a deterministic local preview) — the
    response's `source` field says which one produced the plan.

    Args:
        goal: What you want to accomplish.
        repo_id: Target repository ID (default: mcharness-public-export).
        lane_id: Agent lane to use (default: codex_cli).
    """
    try:
        import asyncio as _asyncio
        from src.warden.api import McHarnessCaptainPlanRequest, create_mcharness_captain_plan

        payload = McHarnessCaptainPlanRequest(goal=goal, repo_id=repo_id, lane_id=lane_id)
        # The endpoint calls asyncio.run() internally (gateway fallback), which
        # would crash on this server's running loop — run it in a worker thread.
        response = await _asyncio.to_thread(create_mcharness_captain_plan, payload)
        plan = response.get("plan") or response
        return _ok("warden_captain_plan", {
            "plan_id": plan.get("plan_id"),
            "title": plan.get("title"),
            "steps": [
                {"id": s.get("step_id"), "title": s.get("title"), "status": s.get("status")}
                for s in (plan.get("steps") or [])
            ],
            "source": response.get("source", plan.get("source", "local_preview")),
            "notes": response.get("notes") or [],
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
async def warden_captain_dispatch_step(plan_id: str, step_id: str) -> str:
    """Dispatch a Captain plan step to the configured CLI runner.

    Uses the same real dispatch path as the web UI: if the runner is enabled
    (MCHARNESS_TMUX_RUNNER_ENABLED + MCHARNESS_CODEX_RUNNER_ENABLED) the step
    actually runs and a watcher tracks it; otherwise a blocked_attempt memory
    is saved honestly and blocked=True is returned. Fail-closed either way.

    Args:
        plan_id: Plan ID to dispatch.
        step_id: Step ID within the plan.
    """
    try:
        import asyncio as _asyncio
        from fastapi import HTTPException
        from src.warden.api import post_mcharness_captain_plan_step_dispatch

        try:
            # The endpoint calls asyncio.run() internally (gateway decision
            # note) — run in a worker thread to avoid nesting event loops.
            response = await _asyncio.to_thread(
                post_mcharness_captain_plan_step_dispatch, plan_id, step_id
            )
        except HTTPException as http_exc:
            return _err("warden_captain_dispatch_step", f"{http_exc.status_code}: {http_exc.detail}")

        return _ok("warden_captain_dispatch_step", {
            "ok": bool(response.get("ok")),
            "blocked": bool(response.get("blocked")),
            "run_id": response.get("run_id"),
            "memory_id": response.get("memory_id"),
            "watcher_id": response.get("watcher_id"),
            "message": response.get("message") or response.get("decision_note") or "",
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
# ---------------------------------------------------------------------------
# Warden Brain tools — local vault + Google hybrid
# ---------------------------------------------------------------------------

@mcp.tool()
def brain_status() -> str:
    """Return status of the Warden Brain (local vault + Google provider)."""
    try:
        from src.warden.brain import local_provider, google_provider
        return _ok("brain_status", {
            "local": local_provider.status(),
            "google": google_provider.status(),
        })
    except Exception as e:
        return _err("brain_status", str(e))


@mcp.tool()
def brain_init_vault() -> str:
    """Initialize the local Obsidian-compatible Markdown vault."""
    try:
        from src.warden.brain.vault import init_vault
        return _ok("brain_init_vault", init_vault())
    except Exception as e:
        return _err("brain_init_vault", str(e))


@mcp.tool()
def brain_reindex() -> str:
    """Scan local vault and reindex all Markdown sources into SQLite FTS."""
    try:
        from src.warden.brain import local_provider
        return _ok("brain_reindex", local_provider.reindex())
    except Exception as e:
        return _err("brain_reindex", str(e))


@mcp.tool()
def brain_list_sources(limit: int = 50) -> str:
    """List indexed brain sources."""
    try:
        from src.warden.brain.index import list_sources
        return _ok("brain_list_sources", {"sources": list_sources(limit=limit)})
    except Exception as e:
        return _err("brain_list_sources", str(e))


@mcp.tool()
def brain_search(query: str, limit: int = 10) -> str:
    """Search the brain (local + Google if enabled). Returns citations."""
    try:
        from src.warden.brain import hybrid
        results = hybrid.search(query, limit=limit)
        return _ok("brain_search", {"query": query, "results": results, "count": len(results)})
    except Exception as e:
        return _err("brain_search", str(e))


@mcp.tool()
def brain_ask(question: str, limit: int = 6) -> str:
    """Ask the brain a question. Returns extractive answer with citations."""
    try:
        from src.warden.brain import hybrid
        answer = hybrid.answer(question, limit=limit)
        return _ok("brain_ask", answer.to_dict())
    except Exception as e:
        return _err("brain_ask", str(e))


@mcp.tool()
def brain_write_note(title: str, body: str, tags: str = "warden,auto") -> str:
    """Write a new Markdown note to the vault inbox. Never overwrites existing files."""
    try:
        from src.warden.brain.vault import write_note
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        result = write_note(title=title, body=body, tags=tag_list)
        return _ok("brain_write_note", result)
    except FileExistsError as e:
        return _err("brain_write_note", f"Note already exists: {e}")
    except ValueError as e:
        return _err("brain_write_note", f"Invalid path: {e}")
    except Exception as e:
        return _err("brain_write_note", str(e))


@mcp.tool()
def brain_google_status() -> str:
    """Return Google Brain provider status."""
    try:
        from src.warden.brain import google_provider
        return _ok("brain_google_status", google_provider.status())
    except Exception as e:
        return _err("brain_google_status", str(e))


@mcp.tool()
def brain_google_mirror(dry_run: bool = True, limit: int = 50) -> str:
    """Mirror local vault sources to Google Discovery Engine."""
    try:
        from src.warden.brain import google_provider
        from src.warden.brain.mirror import mirror_sources
        if not google_provider.is_enabled():
            return _err("brain_google_mirror", "Google Brain not enabled (WARDEN_GOOGLE_BRAIN_ENABLED=1 required)")
        result = mirror_sources(limit=limit, dry_run=dry_run)
        return _ok("brain_google_mirror", result)
    except Exception as e:
        return _err("brain_google_mirror", str(e))


@mcp.tool()
def brain_mirror_status() -> str:
    """Return mirror sync status for local→Google."""
    try:
        from src.warden.brain.mirror import mirror_status
        return _ok("brain_mirror_status", mirror_status())
    except Exception as e:
        return _err("brain_mirror_status", str(e))


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


def _consent_page_html(request_id: str, pending: dict) -> str:
    scope_str = " ".join(pending.get("scopes", []))
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Warden — Authorize {pending.get("client_name", "app")}</title>
<style>body{{font-family:sans-serif;background:#0d1b2e;color:#d4e4f5;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
.card{{background:#14243c;border:1px solid rgba(100,160,255,.25);border-radius:10px;padding:32px 40px;text-align:center;max-width:400px;}}
h2{{margin:0 0 8px;}}p{{color:#8faabf;margin:0 0 16px;}}
input{{width:100%;box-sizing:border-box;padding:8px 10px;border-radius:6px;border:1px solid rgba(100,160,255,.35);background:#0d1b2e;color:#d4e4f5;margin-bottom:16px;}}
.btn{{border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:.9rem;margin:0 6px;}}
.approve{{background:#2d5f9e;color:#d4e4f5;}}.approve:hover{{background:#3a72b8;}}
.deny{{background:#3a2020;color:#e6b8b8;}}.deny:hover{{background:#4a2a2a;}}</style>
</head>
<body><div class="card">
<h2>Authorize {pending.get("client_name", "app")}</h2>
<p>This app is requesting access to your Warden Brain (scope: {scope_str}).</p>
<form method="post" action="/oauth/consent/submit">
<input type="hidden" name="request_id" value="{request_id}">
<input type="password" name="passphrase" placeholder="Owner passphrase" autofocus>
<div>
<button class="btn approve" name="decision" value="approve">Approve</button>
<button class="btn deny" name="decision" value="deny">Deny</button>
</div>
</form>
</div></body></html>"""


def _oauth_denied_html(reason: str = "This authorization request is invalid or has expired.") -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Warden — Not authorized</title>
<style>body{{font-family:sans-serif;background:#0d1b2e;color:#d4e4f5;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
.card{{background:#14243c;border:1px solid rgba(100,160,255,.25);border-radius:10px;padding:32px 40px;text-align:center;max-width:360px;}}</style>
</head><body><div class="card"><h2>Not authorized</h2><p>{reason}</p></div></body></html>"""


async def _handle_oauth_consent_get(scope, receive, send) -> None:
    from starlette.requests import Request
    from starlette.responses import HTMLResponse

    from .mcp_oauth import get_pending_authorization

    request = Request(scope, receive)
    request_id = request.query_params.get("request_id", "")
    pending = get_pending_authorization(request_id) if request_id else None
    if pending is None:
        response = HTMLResponse(_oauth_denied_html(), status_code=400)
    else:
        response = HTMLResponse(_consent_page_html(request_id, pending))
    await response(scope, receive, send)


async def _handle_oauth_consent_submit(scope, receive, send) -> None:
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, RedirectResponse

    from .mcp_oauth import approve_pending_authorization, deny_pending_authorization

    request = Request(scope, receive)
    form = await request.form()
    request_id = form.get("request_id", "")
    decision = form.get("decision", "")
    passphrase = form.get("passphrase", "")

    if decision == "approve":
        redirect_url = approve_pending_authorization(request_id, passphrase)
    else:
        redirect_url = deny_pending_authorization(request_id)

    if redirect_url is None:
        response = HTMLResponse(_oauth_denied_html(), status_code=400)
    else:
        response = RedirectResponse(url=redirect_url, status_code=302)
    await response(scope, receive, send)


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

    hub_status = mcp_hub.bootstrap_hub(mcp)
    log.warning(
        "mcp_hub: reachable_at_boot=%s hub_tools=%d native_tools=%d",
        hub_status.reachable_at_boot, hub_status.hub_tool_count, hub_status.native_tool_count,
    )

    if args.http:
        token = os.getenv("WARDEN_BRAIN_TOKEN", "")
        from .mcp_tokens import list_clients
        if not token and not list_clients() and not os.getenv("MCP_OAUTH_OWNER_PASSPHRASE"):
            print(
                "ERROR: no auth configured for HTTP mode. Set WARDEN_BRAIN_TOKEN, issue a "
                "per-client token (python -m warden.mcp_tokens issue --name <client>), or set "
                "MCP_OAUTH_OWNER_PASSPHRASE to enable the OAuth consent flow.",
                flush=True,
            )
            raise SystemExit(1)

        import uvicorn

        # FastMCP's own ASGI app — handles all routing internally, including
        # the OAuth authorize/token/register/revoke/.well-known routes (added
        # via auth_server_provider=OAuthProvider() above) and the /mcp route's
        # own auth enforcement (RequireAuthMiddleware, backed by
        # OAuthProvider.load_access_token — see mcp_oauth.py for what that
        # accepts: OAuth-issued tokens, Phase 1 per-client tokens, and the
        # legacy shared WARDEN_BRAIN_TOKEN, all unified in one place).
        mcp_app = mcp.streamable_http_app()

        # Pure ASGI wrapper — no Starlette nesting that breaks FastMCP routing.
        # Only special-cases paths FastMCP doesn't serve itself: /health (no
        # auth) and the two consent-screen routes (gated by
        # MCP_OAUTH_OWNER_PASSPHRASE, not a bearer token — see mcp_oauth.py).
        # Everything else — /mcp, /authorize, /token, /register, /revoke,
        # /.well-known/* — is delegated straight to mcp_app, which enforces
        # its own auth where the spec requires it.
        async def app(scope, receive, send):
            if scope["type"] == "lifespan":
                await mcp_app(scope, receive, send)
                return

            if scope["type"] == "http":
                path = scope.get("path", "")

                # Health check — no auth
                if path == "/health":
                    hs = mcp_hub.hub_status()
                    total = len(mcp._tool_manager._tools)
                    body = json.dumps({
                        "ok": True,
                        "server": "warden-brain",
                        "tools": {
                            "warden": hs.native_tool_count,
                            "hub": hs.hub_tool_count,
                            "total": total,
                        },
                        "hub": {
                            "enabled": hs.enabled,
                            "reachable_at_boot": hs.reachable_at_boot,
                            "last_discovery_at": hs.last_discovery_at,
                            "last_error": hs.last_error,
                        },
                    }).encode()
                    await send({"type": "http.response.start", "status": 200,
                                "headers": [[b"content-type", b"application/json"],
                                            [b"content-length", str(len(body)).encode()]]})
                    await send({"type": "http.response.body", "body": body})
                    return

                if path == "/oauth/consent" and scope.get("method") == "GET":
                    await _handle_oauth_consent_get(scope, receive, send)
                    return

                if path == "/oauth/consent/submit" and scope.get("method") == "POST":
                    await _handle_oauth_consent_submit(scope, receive, send)
                    return

                # Everything else (/mcp, /authorize, /token, /register,
                # /revoke, /.well-known/...) is FastMCP's own routing.
                await mcp_app(scope, receive, send)

        log.warning("Warden Brain MCP HTTP server starting on %s:%s", args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    else:
        asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
