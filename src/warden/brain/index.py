"""SQLite FTS5 index for local Markdown vault.

Schema:
  sources(source_id, path, title, tags, headings, word_count, checksum, indexed_at)
  chunks(chunk_id, source_id, path, title, heading, text)
  chunks_fts (FTS5 virtual table over chunks)
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import BrainChunk, BrainSource

log = logging.getLogger(__name__)

DEFAULT_INDEX_PATH = Path.home() / ".warden" / "brain" / "brain.sqlite3"

# Max chars per chunk
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def get_index_path() -> Path:
    raw = os.getenv("WARDEN_BRAIN_INDEX_PATH", "")
    return Path(raw).expanduser() if raw else DEFAULT_INDEX_PATH


def _connect(index_path: Optional[Path] = None) -> sqlite3.Connection:
    p = index_path or get_index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            title TEXT,
            tags TEXT,
            headings TEXT,
            word_count INTEGER,
            checksum TEXT,
            indexed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            path TEXT NOT NULL,
            title TEXT,
            heading TEXT,
            text TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
            USING fts5(
                chunk_id UNINDEXED,
                source_id UNINDEXED,
                path UNINDEXED,
                title,
                heading,
                text,
                content='chunks',
                content_rowid='rowid'
            );

        CREATE TABLE IF NOT EXISTS brain_mirror_status (
            source_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'google_discovery_engine',
            local_checksum TEXT,
            remote_document_id TEXT,
            status TEXT DEFAULT 'pending',
            last_synced_at TEXT,
            last_error TEXT,
            source_path TEXT,
            title TEXT
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_text(text: str, source_id: str, path: str, title: str) -> list[BrainChunk]:
    """Split Markdown body into overlapping paragraph chunks."""
    # Split on headings and paragraph breaks
    sections: list[tuple[str, str]] = []  # (heading, text)
    current_heading = ""
    current_parts: list[str] = []

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            if current_parts:
                sections.append((current_heading, "\n".join(current_parts).strip()))
            current_heading = m.group(2).strip()
            current_parts = []
        else:
            current_parts.append(line)
    if current_parts:
        sections.append((current_heading, "\n".join(current_parts).strip()))

    chunks: list[BrainChunk] = []
    for heading, content in sections:
        # Sub-chunk if content is long
        if not content.strip():
            continue
        words = content.split()
        for i in range(0, len(words), CHUNK_SIZE - CHUNK_OVERLAP):
            chunk_text = " ".join(words[i: i + CHUNK_SIZE])
            if not chunk_text.strip():
                continue
            cid_src = f"{source_id}:{heading}:{i}"
            chunk_id = hashlib.sha256(cid_src.encode()).hexdigest()[:20]
            chunks.append(BrainChunk(
                chunk_id=chunk_id,
                source_id=source_id,
                source_path=path,
                title=title,
                heading=heading,
                text=chunk_text,
            ))
    return chunks


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def reindex_sources(
    sources: list[BrainSource],
    index_path: Optional[Path] = None,
    force: bool = False,
) -> dict:
    """Index/update sources. Skips unchanged (same checksum) unless force=True."""
    conn = _connect(index_path)
    _ensure_schema(conn)

    added = updated = skipped = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    for src in sources:
        try:
            # Check existing
            row = conn.execute(
                "SELECT checksum FROM sources WHERE source_id=?", (src.source_id,)
            ).fetchone()

            if row and row["checksum"] == src.checksum and not force:
                skipped += 1
                continue

            # Read file content for chunking
            fp = Path(src.abs_path) if src.abs_path else None
            if not fp or not fp.exists():
                errors += 1
                continue
            text = fp.read_text(encoding="utf-8", errors="replace")

            # Remove source and old chunks
            conn.execute("DELETE FROM chunks WHERE source_id=?", (src.source_id,))

            # Re-insert source
            conn.execute("""
                INSERT OR REPLACE INTO sources
                  (source_id, path, title, tags, headings, word_count, checksum, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                src.source_id, src.path, src.title,
                " ".join(src.tags),
                " | ".join(src.headings),
                src.word_count, src.checksum, now,
            ))

            # Insert chunks
            chunks = _chunk_text(text, src.source_id, src.path, src.title)
            conn.executemany("""
                INSERT OR REPLACE INTO chunks (chunk_id, source_id, path, title, heading, text)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [(c.chunk_id, c.source_id, c.source_path, c.title, c.heading, c.text) for c in chunks])

            if row:
                updated += 1
            else:
                added += 1
        except Exception as exc:
            log.warning("Error indexing %s: %s", src.path, exc)
            errors += 1

    conn.commit()
    # Rebuild FTS
    try:
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        conn.commit()
    except Exception:
        pass
    conn.close()
    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}


def count_sources(index_path: Optional[Path] = None) -> int:
    conn = _connect(index_path)
    _ensure_schema(conn)
    n = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()
    return n


def list_sources(index_path: Optional[Path] = None, limit: int = 100) -> list[dict]:
    conn = _connect(index_path)
    _ensure_schema(conn)
    rows = conn.execute(
        "SELECT source_id, path, title, tags, word_count, indexed_at FROM sources ORDER BY indexed_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def fts_search(query: str, limit: int = 10, index_path: Optional[Path] = None) -> list[BrainChunk]:
    """Lexical FTS5 search over chunks. Returns top matching chunks."""
    conn = _connect(index_path)
    _ensure_schema(conn)
    try:
        # Escape FTS5 special chars
        safe_q = re.sub(r'["\*\(\)\:\^]', " ", query).strip()
        if not safe_q:
            conn.close()
            return []
        rows = conn.execute("""
            SELECT c.chunk_id, c.source_id, c.path, c.title, c.heading, c.text,
                   bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
        """, (safe_q, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        log.warning("FTS search error: %s", exc)
        conn.close()
        return []
    conn.close()
    return [
        BrainChunk(
            chunk_id=r["chunk_id"],
            source_id=r["source_id"],
            source_path=r["path"],
            title=r["title"],
            heading=r["heading"],
            text=r["text"],
        )
        for r in rows
    ]
