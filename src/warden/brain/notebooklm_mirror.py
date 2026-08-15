"""Local vault + workbench memories → NotebookLM project mirror engine.

Source of truth: local Markdown vault + workbench memories.
Mirror target: Project-scoped NotebookLM bundle directory (and optional Google Drive sync).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .index import _connect, _ensure_schema
from .vault import scan_sources, get_vault_path

log = logging.getLogger(__name__)

SECRET_PATTERNS = re.compile(
    r"(password|secret|token|api_key|private_key|BEGIN\s+RSA|-----BEGIN)\s*[=:]\s*\S+",
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    return SECRET_PATTERNS.sub(r"\1=[REDACTED]", text)


def get_notebooklm_export_dir(project_id: str, vault_path: Optional[Path] = None) -> Path:
    raw = os.getenv("WARDEN_NOTEBOOKLM_MIRROR_DIR", "")
    base = Path(raw).expanduser() if raw else (vault_path or get_vault_path()) / "notebooklm"
    out = base / project_id
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# Mirror status helpers
# ---------------------------------------------------------------------------

def _get_notebooklm_mirror_row(conn, item_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM brain_notebooklm_mirror_status WHERE item_id=?", (item_id,)
    ).fetchone()
    return dict(row) if row else None


def _upsert_notebooklm_mirror_row(conn, item_id: str, **kwargs):
    existing = _get_notebooklm_mirror_row(conn, item_id)
    if existing:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        conn.execute(
            f"UPDATE brain_notebooklm_mirror_status SET {sets} WHERE item_id=?",
            [*kwargs.values(), item_id],
        )
    else:
        kwargs["item_id"] = item_id
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" * len(kwargs))
        conn.execute(
            f"INSERT INTO brain_notebooklm_mirror_status ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )


# ---------------------------------------------------------------------------
# Project source & memory gathering
# ---------------------------------------------------------------------------

def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _match_project_source(src, project_id: str, project_tags: List[str]) -> bool:
    path_lower = src.path.lower()
    pid_lower = project_id.lower()
    if f"10-projects/{pid_lower}" in path_lower or f"projects/{pid_lower}" in path_lower:
        return True
    src_tags_lower = [t.lower() for t in src.tags]
    if pid_lower in src_tags_lower:
        return True
    for pt in project_tags:
        if pt.lower() in src_tags_lower:
            return True
    return False


def _match_project_memory(mem, project_id: str, project_tags: List[str]) -> bool:
    pid_lower = project_id.lower()
    if mem.project_id and mem.project_id.lower() == pid_lower:
        return True
    if mem.scope and mem.scope.lower() == pid_lower:
        return True
    mem_tags_lower = [t.lower() for t in (mem.tags or [])]
    if pid_lower in mem_tags_lower:
        return True
    for pt in project_tags:
        if pt.lower() in mem_tags_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Mirror Engine
# ---------------------------------------------------------------------------

def mirror_project_to_notebooklm(
    project_id: str,
    dry_run: bool = False,
    limit: int = 100,
    vault_path: Optional[Path] = None,
    index_path: Optional[Path] = None,
    workbench_root: Optional[Path] = None,
) -> dict:
    """Mirror project vault notes & workbench memories to NotebookLM bundle.

    Returns summary: {project_id, dry_run, total_items, synced, skipped, errors, would_sync}.
    """
    if not project_id or not re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", project_id, re.IGNORECASE):
        raise ValueError(f"Invalid project_id slug: {project_id!r}")

    vp = vault_path or get_vault_path()
    export_dir = get_notebooklm_export_dir(project_id, vp)

    # Load project info if available
    project_name = project_id
    project_tags: List[str] = [project_id]
    try:
        from src.warden.projects import _load_project
        proj = _load_project(project_id)
        project_name = proj.name
        project_tags = list(dict.fromkeys([project_id] + proj.brain_tags))
    except Exception:
        pass

    # Gather matching sources (exclude any notebooklm export files)
    all_vault_sources = [
        s for s in scan_sources(vp)
        if not s.path.startswith("notebooklm/") and "/notebooklm/" not in s.path
    ]
    project_sources = [
        s for s in all_vault_sources
        if _match_project_source(s, project_id, project_tags)
    ]

    # Gather matching workbench memories
    project_memories = []
    try:
        from src.warden.workbench import WorkbenchStore
        store = WorkbenchStore(root=workbench_root) if workbench_root else WorkbenchStore()
        all_mems = store.list_memories()
        project_memories = [
            m for m in all_mems
            if _match_project_memory(m, project_id, project_tags)
        ]
    except Exception as exc:
        log.warning("Could not load workbench memories for project %s: %s", project_id, exc)

    # Filter out private / local_only items
    project_sources = [
        s for s in project_sources
        if "private" not in s.tags and "local_only" not in s.tags
    ]
    project_memories = [
        m for m in project_memories
        if "private" not in (m.tags or []) and "local_only" not in (m.tags or [])
        and m.status != "forgotten"
    ]

    conn = _connect(index_path)
    _ensure_schema(conn)

    now = datetime.now(timezone.utc).isoformat()
    synced = skipped = errors = 0
    would_sync: list[dict] = []

    # 1. Build Index File ({project_id}_00_index.md)
    index_content_body = [
        f"# Project Index: {project_name}",
        f"",
        f"- **Project ID**: `{project_id}`",
        f"- **Vault Notes Count**: {len(project_sources)}",
        f"- **Workbench Memories Count**: {len(project_memories)}",
        f"- **Tags**: {', '.join(project_tags)}",
        f"",
        f"## Source Documents Overview",
        f"",
    ]
    for s in project_sources[:limit]:
        index_content_body.append(f"- **{s.title}** (`{s.path}`): {s.word_count} words")
    
    index_body_text = _redact("\n".join(index_content_body))
    index_item_id = f"notebooklm-{project_id}-index"
    index_chk = _checksum(index_body_text)
    index_file = export_dir / f"{project_id}_00_index.md"
    index_text = index_body_text + f"\n\n---\nExported At: `{now}`\n"

    row = _get_notebooklm_mirror_row(conn, index_item_id)
    if row and row.get("local_checksum") == index_chk and row.get("status") == "synced" and index_file.exists():
        skipped += 1
    else:
        if dry_run:
            would_sync.append({"item_id": index_item_id, "title": f"Index: {project_name}", "path": str(index_file)})
        else:
            try:
                index_file.write_text(index_text, encoding="utf-8")
                _upsert_notebooklm_mirror_row(
                    conn, index_item_id,
                    project_id=project_id, source_type="index",
                    local_checksum=index_chk, export_path=str(index_file),
                    status="synced", last_synced_at=now, last_error=None,
                    title=f"Index: {project_name}",
                )
                synced += 1
            except Exception as exc:
                _upsert_notebooklm_mirror_row(
                    conn, index_item_id,
                    project_id=project_id, source_type="index",
                    local_checksum=index_chk, export_path=str(index_file),
                    status="error", last_synced_at=now, last_error=str(exc),
                    title=f"Index: {project_name}",
                )
                errors += 1

    # 2. Build Memories File ({project_id}_01_memories.md)
    if project_memories:
        mem_lines = [
            f"# Project Memories & Context: {project_name}",
            f"",
            f"Categorized decisions, facts, constraints, and proof for project `{project_id}`.",
            f"",
        ]
        # Group memories by kind
        by_kind: Dict[str, List[Any]] = {}
        for m in project_memories:
            by_kind.setdefault(m.kind, []).append(m)
        
        for kind, mems in sorted(by_kind.items()):
            mem_lines.append(f"## {kind.upper().replace('_', ' ')}")
            for m in mems:
                mem_lines.append(f"### {m.title or m.summary[:60]}")
                mem_lines.append(f"- **ID**: `{m.memory_id}` | **Source**: `{m.source}`")
                mem_lines.append(f"- **Summary**: {m.summary}")
                if m.notes:
                    mem_lines.append(f"- **Notes**: {m.notes}")
                if m.raw_content:
                    mem_lines.append(f"- **Content**:\n```\n{m.raw_content[:2000]}\n```")
                mem_lines.append("")

        mem_text = _redact("\n".join(mem_lines))
        mem_item_id = f"notebooklm-{project_id}-memories"
        mem_chk = _checksum(mem_text)
        mem_file = export_dir / f"{project_id}_01_memories.md"

        row = _get_notebooklm_mirror_row(conn, mem_item_id)
        if row and row.get("local_checksum") == mem_chk and row.get("status") == "synced" and mem_file.exists():
            skipped += 1
        else:
            if dry_run:
                would_sync.append({"item_id": mem_item_id, "title": f"Memories: {project_name}", "path": str(mem_file)})
            else:
                try:
                    mem_file.write_text(mem_text, encoding="utf-8")
                    _upsert_notebooklm_mirror_row(
                        conn, mem_item_id,
                        project_id=project_id, source_type="memories",
                        local_checksum=mem_chk, export_path=str(mem_file),
                        status="synced", last_synced_at=now, last_error=None,
                        title=f"Memories: {project_name}",
                    )
                    synced += 1
                except Exception as exc:
                    _upsert_notebooklm_mirror_row(
                        conn, mem_item_id,
                        project_id=project_id, source_type="memories",
                        local_checksum=mem_chk, export_path=str(mem_file),
                        status="error", last_synced_at=now, last_error=str(exc),
                        title=f"Memories: {project_name}",
                    )
                    errors += 1

    # 3. Process Vault Notes
    for src in project_sources[:limit]:
        fp = Path(src.abs_path) if src.abs_path else vp / src.path
        if not fp.exists():
            errors += 1
            continue
        try:
            raw_note = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            errors += 1
            continue
        
        safe_note = _redact(raw_note)
        note_chk = _checksum(safe_note)
        item_id = f"notebooklm-{project_id}-vault-{src.source_id}"
        
        # Clean target filename
        safe_stem = re.sub(r"[^\w-]", "_", src.title.lower()).strip("_")[:40] or "note"
        target_file = export_dir / f"{project_id}_note_{safe_stem}_{src.source_id[:8]}.md"

        row = _get_notebooklm_mirror_row(conn, item_id)
        if row and row.get("local_checksum") == note_chk and row.get("status") == "synced" and target_file.exists():
            skipped += 1
            continue

        if dry_run:
            would_sync.append({"item_id": item_id, "title": src.title, "path": str(target_file)})
            continue

        try:
            target_file.write_text(safe_note, encoding="utf-8")
            _upsert_notebooklm_mirror_row(
                conn, item_id,
                project_id=project_id, source_type="vault",
                local_checksum=note_chk, export_path=str(target_file),
                status="synced", last_synced_at=now, last_error=None,
                title=src.title,
            )
            synced += 1
        except Exception as exc:
            _upsert_notebooklm_mirror_row(
                conn, item_id,
                project_id=project_id, source_type="vault",
                local_checksum=note_chk, export_path=str(target_file),
                status="error", last_synced_at=now, last_error=str(exc),
                title=src.title,
            )
            errors += 1

    conn.commit()
    conn.close()

    total_items = 1 + (1 if project_memories else 0) + len(project_sources[:limit])

    return {
        "project_id": project_id,
        "project_name": project_name,
        "dry_run": dry_run,
        "total_items": total_items,
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "export_dir": str(export_dir),
        "would_sync": would_sync if dry_run else [],
    }


# ---------------------------------------------------------------------------
# Status report helper
# ---------------------------------------------------------------------------

def notebooklm_mirror_status(
    project_id: Optional[str] = None,
    index_path: Optional[Path] = None,
) -> dict:
    """Return NotebookLM mirror sync status."""
    conn = _connect(index_path)
    _ensure_schema(conn)

    if project_id:
        rows = conn.execute("""
            SELECT item_id, project_id, source_type, title, status, local_checksum,
                   export_path, last_synced_at, last_error
            FROM brain_notebooklm_mirror_status
            WHERE project_id=?
            ORDER BY last_synced_at DESC
            LIMIT 100
        """, (project_id,)).fetchall()
        counts = conn.execute("""
            SELECT status, COUNT(*) as n FROM brain_notebooklm_mirror_status
            WHERE project_id=? GROUP BY status
        """, (project_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT item_id, project_id, source_type, title, status, local_checksum,
                   export_path, last_synced_at, last_error
            FROM brain_notebooklm_mirror_status
            ORDER BY last_synced_at DESC
            LIMIT 100
        """).fetchall()
        counts = conn.execute("""
            SELECT status, COUNT(*) as n FROM brain_notebooklm_mirror_status GROUP BY status
        """).fetchall()

    conn.close()
    return {
        "project_id": project_id,
        "records": [dict(r) for r in rows],
        "counts": {r["status"]: r["n"] for r in counts},
    }
