"""sqlite-vec vector store with graceful fallback when extension is absent."""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MCTABLE_ROOT = Path(os.getenv("MCHARNESS_DATA_ROOT", "_mctable"))
DB_PATH = MCTABLE_ROOT / "brain_vectors.db"

_SQLITE_VEC_AVAILABLE: Optional[bool] = None


def _check_vec() -> bool:
    global _SQLITE_VEC_AVAILABLE
    if _SQLITE_VEC_AVAILABLE is None:
        try:
            import sqlite_vec  # noqa: F401
            _SQLITE_VEC_AVAILABLE = True
        except ImportError:
            _SQLITE_VEC_AVAILABLE = False
            log.info("sqlite-vec not installed — using cosine fallback store")
    return _SQLITE_VEC_AVAILABLE


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    if _check_vec():
        import sqlite_vec
        sqlite_vec.load(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS brain_vectors "
        "(memory_id TEXT PRIMARY KEY, embedding TEXT, meta TEXT)"
    )
    conn.commit()
    return conn


def upsert(memory_id: str, embedding: list[float], meta: dict | None = None) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO brain_vectors(memory_id, embedding, meta) VALUES(?,?,?)",
            (memory_id, json.dumps(embedding), json.dumps(meta or {})),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("brain_vector_store upsert failed: %s", exc)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def search(query_embedding: list[float], limit: int = 10) -> list[dict]:
    """Return [{memory_id, score}] ranked by cosine similarity."""
    try:
        conn = _get_conn()
        rows = conn.execute("SELECT memory_id, embedding FROM brain_vectors").fetchall()
        conn.close()
        scored = []
        for (mid, emb_json) in rows:
            try:
                emb = json.loads(emb_json)
                score = _cosine(query_embedding, emb)
                scored.append({"memory_id": mid, "score": round(score, 4)})
            except Exception:
                continue
        scored.sort(key=lambda r: -r["score"])
        return scored[:limit]
    except Exception as exc:
        log.warning("brain_vector_store search failed: %s", exc)
        return []


def count() -> int:
    try:
        conn = _get_conn()
        n = conn.execute("SELECT COUNT(*) FROM brain_vectors").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0
