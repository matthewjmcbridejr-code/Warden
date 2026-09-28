"""Where agents wrote: Cloud SQL memory, MCP calls, missions, notes, artifacts.

Production Warden is the cloud control plane (Cloud SQL, the authenticated MCP
edge, and the Vercel console). Port 6969 on mclab, formerly mcserver2, was the
old McServer UI and is not this feed. Tool arguments and note bodies are not
copied. MCP calls land in Cloud SQL when ``WARDEN_BRAIN_BACKEND=postgres``;
otherwise a process-local journal is only a non-authoritative fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.warden.paths import data_root
from src.warden.workbench import redact_memory_text

_LOCK = threading.Lock()
_JOURNAL_NAME = "mcp-calls.jsonl"
_RUNTIME_NAME = "mcp-runtime.json"
_MAX_JOURNAL_BYTES = 1_500_000
_JOURNAL_KEEP_LINES = 1500
_TEXT_LIMIT = 160
_FRONTMATTER_BYTES = 2048
_VAULT_WALK_CAP = 1500

_MEMORY_TOOLS = frozenset({
    "warden_remember",
    "warden_ingest",
    "warden_update_me",
})
_BOARD_TOOLS = frozenset({
    "warden_post_task",
    "warden_claim_task",
    "warden_handoff",
    "warden_complete_task",
    "warden_update_task",
    "warden_cancel_task",
    "warden_supersede_task",
    "warden_resolve_issue",
})
_ARTIFACT_TOOLS = frozenset({
    "warden_artifact_store",
})


def activity_dir() -> Path:
    raw = os.getenv("WARDEN_ACTIVITY_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return data_root() / "activity"


def classify_tool(name: str) -> str:
    """Landing place for one MCP tool call, using the tool's real job."""
    tool = (name or "").strip()
    if tool in _MEMORY_TOOLS or tool.startswith("warden_memory"):
        return "memory"
    if tool in _BOARD_TOOLS:
        return "board"
    if tool in _ARTIFACT_TOOLS or tool.startswith("warden_artifact_"):
        return "artifact"
    if tool.startswith("brain_"):
        return "brain"
    return "mcp"


def _clip(value: Any, limit: int = _TEXT_LIMIT) -> str:
    redacted = redact_memory_text("" if value is None else str(value)) or ""
    redacted = " ".join(redacted.split())
    if len(redacted) > limit:
        return redacted[: limit - 1].rstrip() + "…"
    return redacted


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    text = str(value or "").strip()
    return text


def _event_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _event(
    *,
    at: str,
    destination: str,
    action: str,
    title: str,
    agent: Optional[str] = None,
    tool: str = "",
    ref: str = "",
    project: str = "",
    ok: bool = True,
    detail: str = "",
    landed: str = "",
) -> dict[str, Any]:
    agent_text = _clip(agent, 80) if agent else ""
    return {
        "id": _event_id(destination, at, ref, agent_text, title, action),
        "at": at or "",
        "agent": agent_text or None,
        "destination": destination,
        "landed": landed or destination,
        "action": action,
        "tool": tool,
        "title": _clip(title, 180) or action,
        "ref": _clip(ref, 180),
        "project": _clip(project, 80),
        "ok": bool(ok),
        "detail": _clip(detail, 180),
    }


def _append_journal(record: dict[str, Any]) -> None:
    directory = activity_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _JOURNAL_NAME
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _LOCK:
        if path.exists() and path.stat().st_size > _MAX_JOURNAL_BYTES:
            kept = path.read_text(encoding="utf-8", errors="replace").splitlines()[-_JOURNAL_KEEP_LINES:]
            path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def _cloud_enabled() -> bool:
    try:
        from src.warden.cloud_control_plane import cloud_control_enabled
        return bool(cloud_control_enabled())
    except Exception:
        return False


def _cloud_primary() -> bool:
    try:
        from src.warden.cloud_brain import is_cloud_primary
        return bool(is_cloud_primary())
    except Exception:
        return False


def _mcp_call_payload(*, agent: str, tool: str, ok: bool, ref: str, error: str) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": _clip(agent, 80) or "unknown",
        "tool": _clip(tool, 80),
        "destination": "mcp",
        "landed": classify_tool(tool),
        "ok": bool(ok),
        "ref": _clip(ref, 180),
        "error": _clip(error, 180),
    }


def record_mcp_call(
    *,
    agent: str,
    tool: str,
    ok: bool,
    ref: str = "",
    error: str = "",
) -> None:
    """Record one MCP call. Arguments are never accepted or stored.

    Cloud SQL is the authority when the cloud backend is on. A JSONL file is
    only the fallback when Cloud SQL is not configured or the write fails.
    """
    payload = _mcp_call_payload(agent=agent, tool=tool, ok=ok, ref=ref, error=error)
    if _cloud_enabled():
        try:
            from src.warden.cloud_control_plane import CloudControlPlane
            record_id = _event_id(payload["ts"], payload["agent"], payload["tool"], payload["ref"])
            CloudControlPlane().upsert_record(
                "mcp_call", record_id, payload, source_updated_at=payload["ts"],
            )
            return
        except Exception:
            pass
    try:
        _append_journal(payload)
    except Exception:
        return


def write_mcp_runtime_status(status: dict[str, Any]) -> None:
    """Persist credential-free MCP process counts for the local dashboard."""
    try:
        upstreams = []
        for row in status.get("upstreams") or []:
            if not isinstance(row, dict):
                continue
            upstreams.append({
                "name": _clip(row.get("name"), 40),
                "reachable": bool(row.get("reachable")),
                "tool_count": int(row.get("tool_count") or 0),
                "error": _clip(row.get("error"), 160) or None,
            })
        payload = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "native_tool_count": int(status.get("native_tool_count") or 0),
            "hub_tool_count": int(status.get("hub_tool_count") or 0),
            "upstreams": upstreams,
        }
        directory = activity_dir()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / _RUNTIME_NAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if _cloud_enabled():
            from src.warden.cloud_control_plane import CloudControlPlane
            CloudControlPlane().upsert_record(
                "mcp_runtime", "current", payload, source_updated_at=payload["recorded_at"],
            )
    except Exception:
        return


def read_mcp_runtime_status() -> Optional[dict[str, Any]]:
    if _cloud_enabled():
        try:
            rows = _cloud_rows("mcp_runtime", 1)
            if rows:
                return rows[0]
        except Exception:
            pass
    path = activity_dir() / _RUNTIME_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _result_text(result: Any) -> str:
    if isinstance(result, str):
        return result[:4000]
    if isinstance(result, dict):
        try:
            return json.dumps(result)[:4000]
        except Exception:
            return ""
    parts: list[str] = []
    blocks = getattr(result, "content", None)
    if blocks is None and isinstance(result, (list, tuple)):
        blocks = result
    if isinstance(blocks, (list, tuple)):
        for block in blocks:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                parts.append(str(text))
    return "\n".join(parts)[:4000]


def _summarize_tool_result(result: Any) -> tuple[bool, str, str]:
    ok = not bool(getattr(result, "isError", False))
    ref = ""
    error = ""
    text = _result_text(result)
    if not text:
        return ok, ref, error
    try:
        payload = json.loads(text)
    except Exception:
        return ok, ref, error
    if not isinstance(payload, dict):
        return ok, ref, error
    if payload.get("ok") is False:
        ok = False
        error = str(payload.get("error") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if isinstance(data, dict):
        for key in ("memory_id", "path", "task_id", "artifact_id", "file"):
            if data.get(key):
                ref = str(data[key])
                break
    return ok, ref, error


def install_mcp_call_journal(mcp: Any) -> None:
    """Record tool name, caller, and outcome for every FastMCP tool call."""
    manager = getattr(mcp, "_tool_manager", None)
    if manager is None or getattr(manager, "_warden_activity_traced", False):
        return
    original = manager.call_tool

    async def traced_call_tool(name, arguments, context=None, convert_result=False):
        agent = "local-stdio"
        try:
            from src.warden.brain_mcp_server import _current_caller_identity
            agent = _current_caller_identity().get("agent_id") or agent
        except Exception:
            agent = os.getenv("WARDEN_AGENT_ID", "").strip() or agent
        try:
            result = await original(name, arguments, context=context, convert_result=convert_result)
        except Exception as exc:
            record_mcp_call(agent=agent, tool=str(name), ok=False, error=type(exc).__name__)
            raise
        ok, ref, error = _summarize_tool_result(result)
        record_mcp_call(agent=agent, tool=str(name), ok=ok, ref=ref, error=error)
        return result

    manager.call_tool = traced_call_tool
    manager._warden_activity_traced = True


def _read_journal(limit: int, journal_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    path = (journal_dir or activity_dir()) / _JOURNAL_NAME
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    events: list[dict[str, Any]] = []
    for line in lines[-max(limit * 4, limit):]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        tool = str(row.get("tool") or "")
        landed = str(row.get("landed") or classify_tool(tool))
        if landed not in {"brain", "memory", "mcp", "board", "artifact"}:
            landed = "mcp"
        ok = bool(row.get("ok", True))
        title = tool or "MCP call"
        if not ok and row.get("error"):
            title = f"{tool} failed"
        events.append(_event(
            at=_iso(row.get("ts")),
            destination="mcp",
            landed=landed,
            action="call",
            title=title,
            agent=str(row.get("agent") or "") or None,
            tool=tool,
            ref=str(row.get("ref") or ""),
            ok=ok,
            detail=str(row.get("error") or ""),
        ))
    return events


def _cloud_rows(record_type: str, limit: int) -> list[dict[str, Any]]:
    from src.warden.cloud_control_plane import CloudControlPlane
    rows = CloudControlPlane().list_records(record_type, limit=limit)
    return [row for row in rows if isinstance(row, dict)]


def _mcp_events(limit: int, journal_dir: Optional[Path] = None) -> tuple[list[dict[str, Any]], str]:
    cloud_detail = (
        "Cloud SQL mcp_call records from the cloud MCP edge. "
        "Tool arguments are not stored. Calls from before this log started are absent."
    )
    if _cloud_enabled() and journal_dir is None:
        try:
            rows = _cloud_rows("mcp_call", limit)
            events = []
            for row in rows:
                tool = str(row.get("tool") or "")
                landed = str(row.get("landed") or classify_tool(tool))
                if landed not in {"brain", "memory", "mcp", "board", "artifact"}:
                    landed = "mcp"
                ok = bool(row.get("ok", True))
                title = f"{tool} failed" if (not ok and row.get("error")) else (tool or "MCP call")
                events.append(_event(
                    at=_iso(row.get("ts")),
                    destination="mcp",
                    landed=landed,
                    action="call",
                    title=title,
                    agent=str(row.get("agent") or "") or None,
                    tool=tool,
                    ref=str(row.get("ref") or ""),
                    ok=ok,
                    detail=str(row.get("error") or ""),
                ))
            return events, cloud_detail
        except Exception as exc:
            fallback = _read_journal(limit, journal_dir)
            return fallback, _clip(
                "Cloud SQL MCP log unavailable (" + type(exc).__name__ + "). "
                "The process-local journal is not the cloud authority.",
                180,
            )
    local = _read_journal(limit, journal_dir)
    return local, (
        "Process-local MCP journal because WARDEN_BRAIN_BACKEND is not postgres. "
        "Production calls are stored in Cloud SQL, not on mclab."
    )


def _cloud_artifact_events(limit: int) -> list[dict[str, Any]]:
    events = []
    for row in _cloud_rows("artifact", limit):
        events.append(_event(
            at=_iso(row.get("created_at") or row.get("updated_at")),
            destination="artifact",
            action="artifact",
            title=str(row.get("artifact_id") or "artifact"),
            agent=str(row.get("created_by") or "") or None,
            ref=str(row.get("uri") or row.get("artifact_id") or ""),
            detail="Cloud SQL artifact record. File bytes are not returned.",
        ))
    return events


def _cloud_mission_events(limit: int) -> list[dict[str, Any]]:
    events = []
    for row in _cloud_rows("mission", limit):
        body = row.get("body") if isinstance(row.get("body"), dict) else {}
        title = str(body.get("title") or row.get("kind") or row.get("mission_id") or "mission")
        events.append(_event(
            at=_iso(row.get("updated_at") or row.get("created_at")),
            destination="board",
            action=str(row.get("status") or row.get("kind") or "mission"),
            title=title,
            agent=str(row.get("worker_id") or row.get("owner_id") or "") or None,
            ref=str(row.get("mission_id") or ""),
            project=str(body.get("project") or ""),
            ok=str(row.get("status") or "") not in {"failed", "error"},
            detail="Cloud SQL mission.",
        ))
    return events


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            chunk = handle.read(_FRONTMATTER_BYTES)
    except Exception:
        return {}
    if not chunk.startswith("---"):
        return {}
    end = chunk.find("\n---", 3)
    if end < 0:
        return {}
    data: dict[str, str] = {}
    for line in chunk[3:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key:
            data[key] = value.strip().strip('"').strip("'")
    return data


def _brain_events(limit: int, vault_path: Optional[Path] = None) -> tuple[list[dict[str, Any]], str]:
    from src.warden.brain.vault import get_vault_path

    root = vault_path or get_vault_path()
    if not root.exists():
        return [], "Brain vault is not on disk yet."
    found: list[tuple[float, Path]] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in {".git", ".obsidian", ".trash", "node_modules"}]
        for filename in filenames:
            if seen >= _VAULT_WALK_CAP:
                break
            if not filename.endswith(".md"):
                continue
            seen += 1
            path = Path(dirpath) / filename
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
        if seen >= _VAULT_WALK_CAP:
            break
    found.sort(key=lambda item: item[0], reverse=True)
    events: list[dict[str, Any]] = []
    for mtime, path in found[:limit]:
        meta = _frontmatter(path)
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = path.name
        agent = meta.get("agent") or meta.get("created_by") or ""
        title = meta.get("title") or path.stem
        at = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
        events.append(_event(
            at=at,
            destination="brain",
            action="note",
            title=title,
            agent=agent or None,
            ref=rel,
            detail=meta.get("source") or meta.get("tags") or "",
        ))
    note = (
        "Markdown vault frontmatter on this service only. Note bodies are not returned. "
        "Structured memory authority is Cloud SQL, not a directory on mclab."
    )
    if not events:
        note = "Vault exists and has no markdown notes yet. " + note
    return events, note


def _memory_and_artifact_events(limit: int, memory_store: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if memory_store is not None:
        store = memory_store
    else:
        from src.warden.cloud_brain import get_memory_store
        store = get_memory_store()
    memories = []
    for memory in store.list_memories():
        if getattr(memory, "status", "") == "forgotten":
            continue
        memories.append(_event(
            at=_iso(memory.updated_at),
            destination="memory",
            action=str(memory.kind or "write"),
            title=memory.title or memory.summary or memory.memory_id,
            agent=memory.agent_id,
            ref=memory.memory_id,
            project=memory.project_id or memory.scope or "",
            detail=memory.source or "",
        ))
        if len(memories) >= limit:
            break
    artifacts = []
    if _cloud_enabled():
        return memories, artifacts
    for artifact in store.list_artifacts():
        artifacts.append(_event(
            at=_iso(artifact.updated_at),
            destination="artifact",
            action=str(artifact.kind or "artifact"),
            title=artifact.title or artifact.artifact_id,
            agent=None,
            ref=artifact.artifact_id,
            detail="Local workbench artifact. Cloud artifact authority is the Cloud SQL artifact record.",
        ))
        if len(artifacts) >= limit:
            break
    return memories, artifacts


def _board_events(limit: int, board_root: Optional[Path] = None) -> list[dict[str, Any]]:
    root = board_root
    if root is None:
        root = Path(os.getenv("WARDEN_BOARD_ROOT", os.getenv("MCTABLE_BOARD_ROOT", "~/.local/share/warden/board"))).expanduser()
    act_root = root / "activity"
    if not act_root.exists():
        return []
    events: list[dict[str, Any]] = []
    day_dirs = sorted((path for path in act_root.iterdir() if path.is_dir()), reverse=True)[:5]
    for day_dir in day_dirs:
        files = sorted(day_dir.glob("*.jsonl"), reverse=True)
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                action = str(row.get("action") or row.get("event") or "activity")
                title = row.get("note") or row.get("warning") or action
                agent = row.get("agent") or row.get("from_agent") or ""
                ref = str(row.get("task") or row.get("task_id") or "")
                detail = ""
                if row.get("to"):
                    detail = f"to {row.get('to')}"
                events.append(_event(
                    at=_iso(row.get("ts")),
                    destination="board",
                    action=action,
                    title=str(title),
                    agent=str(agent) if agent else None,
                    ref=ref,
                    project=str(row.get("project") or row.get("project_id") or ""),
                    ok=action not in {"workspace_drift_blocked"},
                    detail=detail,
                ))
                if len(events) >= limit:
                    return events
    return events


def build_activity_feed(
    *,
    limit: int = 80,
    destination: str = "",
    include_memory: bool = True,
    memory_unavailable_reason: str = "",
    memory_store: Any = None,
    vault_path: Optional[Path] = None,
    board_root: Optional[Path] = None,
    journal_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Merge recent writes. `destination` limits the feed to one landing place."""
    limit = max(1, min(int(limit), 200))
    want = (destination or "").strip().lower()
    # Unfiltered views keep a slice of each landing place so one busy store
    # cannot hide brain, memory, or MCP rows.
    per_source = limit if want else min(limit, 40)
    allowed = {"", "brain", "memory", "mcp", "board", "artifact"}
    if want not in allowed:
        want = ""

    coverage: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    if include_memory and (not want or want in {"memory", "artifact"}):
        try:
            memories, artifacts = _memory_and_artifact_events(per_source, memory_store)
        except Exception as exc:
            memories, artifacts = [], []
            include_memory = False
            memory_unavailable_reason = _clip(type(exc).__name__ + " while reading memory", 180)
        else:
            if not want or want == "memory":
                events.extend(memories)
            if not want or want == "artifact":
                events.extend(artifacts)
    else:
        memories, artifacts = [], []

    cloud_on = _cloud_enabled()
    if cloud_on and (not want or want == "artifact"):
        try:
            events.extend(_cloud_artifact_events(per_source))
            artifact_detail = "Cloud SQL artifact records, including created_by. File bytes are not returned."
        except Exception as exc:
            artifact_detail = _clip("Cloud SQL artifacts unavailable: " + type(exc).__name__, 180)
    elif _cloud_primary():
        artifact_detail = "Cloud SQL is the artifact authority. This response did not load artifact rows."
    else:
        artifact_detail = (
            "Local workbench artifacts. Production artifact records live in Cloud SQL, not on mclab."
        )
    if include_memory:
        memory_detail = (
            "Cloud SQL memories with the stored agent id, kind, title, and project. Bodies are not returned."
            if _cloud_primary()
            else "Local workbench cache. Production memory authority is Cloud SQL when WARDEN_BRAIN_BACKEND=postgres."
        )
        coverage.append({
            "id": "memory",
            "label": "Memory",
            "included": True,
            "detail": memory_detail,
        })
        coverage.append({
            "id": "artifact",
            "label": "Artifacts",
            "included": True,
            "detail": artifact_detail,
        })
    else:
        coverage.append({
            "id": "memory",
            "label": "Memory",
            "included": False,
            "detail": memory_unavailable_reason or "Memory is not available on this service.",
        })
        coverage.append({
            "id": "artifact",
            "label": "Workbench artifacts",
            "included": False,
            "detail": "Artifact listing uses the same private memory store, which is not available here.",
        })

    if not want or want == "brain":
        try:
            brain_events, brain_detail = _brain_events(per_source, vault_path)
            events.extend(brain_events)
        except Exception as exc:
            brain_detail = _clip("Brain vault could not be read: " + type(exc).__name__, 180)
        coverage.append({
            "id": "brain",
            "label": "Brain notes",
            "included": True,
            "detail": brain_detail,
        })
    else:
        coverage.append({
            "id": "brain",
            "label": "Brain notes",
            "included": True,
            "detail": "Vault markdown frontmatter. Hidden by the current filter.",
        })

    if not want or want == "board":
        if cloud_on:
            try:
                events.extend(_cloud_mission_events(per_source))
                board_detail = "Cloud SQL mission records. The old lab-machine board log is not the authority."
            except Exception as exc:
                board_detail = _clip("Cloud SQL missions unavailable: " + type(exc).__name__, 180)
                try:
                    events.extend(_board_events(per_source, board_root))
                except Exception:
                    pass
        else:
            try:
                events.extend(_board_events(per_source, board_root))
            except Exception:
                pass
            board_detail = (
                "Local board files. Production missions live in Cloud SQL when WARDEN_BRAIN_BACKEND=postgres."
            )
    else:
        board_detail = "Mission and board rows are hidden by the current filter."
    coverage.append({
        "id": "board",
        "label": "Missions",
        "included": True,
        "detail": board_detail,
    })

    mcp_rows, mcp_detail = _mcp_events(per_source, journal_dir)
    events.extend(mcp_rows)

    runtime = read_mcp_runtime_status() if journal_dir is None else None
    if journal_dir is not None:
        runtime_path = journal_dir / _RUNTIME_NAME
        if runtime_path.exists():
            try:
                runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            except Exception:
                runtime = None
    if runtime:
        native = runtime.get("native_tool_count")
        hub = runtime.get("hub_tool_count")
        mcp_detail = f"MCP process last recorded {native} native tools and {hub} hub tools. " + mcp_detail
    coverage.append({
        "id": "mcp",
        "label": "MCP calls",
        "included": True,
        "detail": mcp_detail,
    })

    # Journal rows and stored records can describe the same write. Keep one
    # copy of each event id.
    def _matches(row: dict[str, Any]) -> bool:
        if not want:
            return True
        if want == "mcp":
            return row.get("action") == "call" or row.get("destination") == "mcp"
        return row.get("destination") == want or row.get("landed") == want

    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in events:
        if not _matches(row):
            continue
        if row["id"] in seen_ids:
            continue
        seen_ids.add(row["id"])
        deduped.append(row)
    deduped.sort(key=lambda row: row.get("at") or "", reverse=True)
    cap = limit if want else min(200, per_source * 5)
    deduped = deduped[:cap]
    counts: dict[str, int] = {}
    for row in deduped:
        counts[row["destination"]] = counts.get(row["destination"], 0) + 1
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(deduped),
        "counts": counts,
        "destination": want or "all",
        "placement": {
            "control_plane": "cloud" if _cloud_primary() else "local-cache",
            "console_path": os.getenv("WARDEN_DASH_PUBLIC_URL", "https://mcp.mctable.online/dash"),
            "retired_local_ui": (
                "Port 6969 on mclab (formerly mcserver2) was the old McServer dashboard. "
                "The Cloud Run URL is private. The operator dashboard is /dash on the MCP edge."
            ),
        },
        "coverage": coverage,
        "mcp_runtime": runtime,
        "events": deduped,
    }
