"""Local vault → Google Discovery Engine mirror engine.

Source of truth: local Markdown vault.
Mirror: Google managed index (one-way, local → Google).

Mirror metadata stored in brain.sqlite3: brain_mirror_status table.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .index import _connect, _ensure_schema
from .vault import scan_sources, get_vault_path

log = logging.getLogger(__name__)

SECRET_PATTERNS = re.compile(
    r"(password|secret|token|api_key|private_key|BEGIN\s+RSA)\s*[=:]\s*\S+",
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    return SECRET_PATTERNS.sub(r"\1=[REDACTED]", text)


def _remote_doc_id(source_id: str) -> str:
    return f"warden-{source_id}"


# ---------------------------------------------------------------------------
# Mirror status table helpers
# ---------------------------------------------------------------------------

def _get_mirror_row(conn, source_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM brain_mirror_status WHERE source_id=?", (source_id,)
    ).fetchone()
    return dict(row) if row else None


def _upsert_mirror_row(conn, source_id: str, **kwargs):
    existing = _get_mirror_row(conn, source_id)
    if existing:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        conn.execute(
            f"UPDATE brain_mirror_status SET {sets} WHERE source_id=?",
            [*kwargs.values(), source_id],
        )
    else:
        kwargs["source_id"] = source_id
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" * len(kwargs))
        conn.execute(f"INSERT INTO brain_mirror_status ({cols}) VALUES ({placeholders})", list(kwargs.values()))


# ---------------------------------------------------------------------------
# Document builder
# ---------------------------------------------------------------------------

def _build_document(source, vault_path: Path) -> Optional[dict]:
    fp = Path(source.abs_path) if source.abs_path else vault_path / source.path
    if not fp.exists():
        return None
    try:
        raw = fp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    safe = _redact(raw)
    return {
        "id": _remote_doc_id(source.source_id),
        "json_data": {
            "title": source.title,
            "path": source.path,
            "tags": source.tags,
            "headings": source.headings,
            "content": safe,
            "source_id": source.source_id,
            "provider": "local",
        },
    }


# ---------------------------------------------------------------------------
# Mirror engine
# ---------------------------------------------------------------------------

def mirror_sources(
    source_ids: Optional[list[str]] = None,
    limit: int = 50,
    dry_run: bool = False,
    vault_path=None,
    index_path=None,
) -> dict:
    """Mirror local vault sources to Google Discovery Engine.

    Returns summary: {synced, skipped, errors, dry_run, would_sync}.
    """
    from . import google_provider as gp

    vp = vault_path or get_vault_path()
    all_sources = scan_sources(vp)

    if source_ids:
        all_sources = [s for s in all_sources if s.source_id in source_ids]

    all_sources = all_sources[:limit]

    conn = _connect(index_path)
    _ensure_schema(conn)

    now = datetime.now(timezone.utc).isoformat()
    synced = skipped = errors = 0
    would_sync: list[dict] = []

    for src in all_sources:
        # Notes tagged "private" or "local_only" (e.g. dropzone financial docs)
        # never leave the local vault, regardless of mirror config.
        if "private" in src.tags or "local_only" in src.tags:
            skipped += 1
            continue

        row = _get_mirror_row(conn, src.source_id)
        if row and row.get("local_checksum") == src.checksum and row.get("status") == "synced":
            skipped += 1
            continue

        if dry_run:
            would_sync.append({"source_id": src.source_id, "path": src.path, "title": src.title})
            continue

        # Build document payload
        doc = _build_document(src, vp)
        if doc is None:
            _upsert_mirror_row(conn, src.source_id,
                provider="google_discovery_engine",
                source_path=src.path, title=src.title,
                local_checksum=src.checksum,
                status="error", last_error="File not found", last_synced_at=now)
            errors += 1
            continue

        # Push to Google
        try:
            _push_document(doc)
            _upsert_mirror_row(conn, src.source_id,
                provider="google_discovery_engine",
                source_path=src.path, title=src.title,
                local_checksum=src.checksum,
                remote_document_id=doc["id"],
                status="synced", last_error=None, last_synced_at=now)
            synced += 1
        except Exception as exc:
            log.warning("Mirror failed for %s: %s", src.path, exc)
            _upsert_mirror_row(conn, src.source_id,
                provider="google_discovery_engine",
                source_path=src.path, title=src.title,
                local_checksum=src.checksum,
                status="error", last_error=str(exc), last_synced_at=now)
            errors += 1

    conn.commit()
    conn.close()

    return {
        "dry_run": dry_run,
        "total_sources": len(all_sources),
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "would_sync": would_sync if dry_run else [],
    }


# Injected in tests
_document_pusher = None


def set_document_pusher(fn):
    global _document_pusher
    _document_pusher = fn


def _push_document(doc: dict) -> None:
    """Push a document to Google Discovery Engine."""
    if _document_pusher is not None:
        _document_pusher(doc)
        return

    from . import google_provider as gp
    cfg = gp.get_config()
    client, err = gp._get_client()
    if client is None:
        raise RuntimeError(f"Google client unavailable: {err}")

    try:
        from google.cloud import discoveryengine_v1 as de

        parent = (
            f"projects/{cfg['project_id']}/locations/{cfg['location']}"
            f"/collections/{cfg['collection_id']}"
            f"/dataStores/{cfg['data_store_id']}/branches/default_branch"
        )
        document = de.Document(
            id=doc["id"],
            json_data=str(doc["json_data"]),
        )
        client.update_document(
            de.UpdateDocumentRequest(document=document, allow_missing=True)
        )
    except ImportError:
        raise RuntimeError("google-cloud-discoveryengine not installed")


# ---------------------------------------------------------------------------
# Mirror status report
# ---------------------------------------------------------------------------

def mirror_status(index_path=None) -> dict:
    conn = _connect(index_path)
    _ensure_schema(conn)
    rows = conn.execute("""
        SELECT source_id, source_path, title, status, local_checksum,
               remote_document_id, last_synced_at, last_error
        FROM brain_mirror_status
        ORDER BY last_synced_at DESC
        LIMIT 100
    """).fetchall()
    counts = conn.execute("""
        SELECT status, COUNT(*) as n FROM brain_mirror_status GROUP BY status
    """).fetchall()
    conn.close()
    return {
        "records": [dict(r) for r in rows],
        "counts": {r["status"]: r["n"] for r in counts},
    }
