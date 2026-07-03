"""SQLite persistence for the resident agent.

Tables:
  offsets            — Telegram getUpdates offset (per transport)
  conversation_log    — rolling per-chat conversation summaries
  watchers            — watcher definitions/state (mirrors watchers.Watcher)
  approvals           — approval queue
  notifications       — sent-notification hash log for dedup
  audit_log           — append-only action audit trail

No secrets are ever stored in this database.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResidentState:
    """Thin SQLite wrapper. One instance per db path; safe for reuse across a process."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with _LOCK:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS offsets (
                    transport TEXT PRIMARY KEY,
                    offset INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS conversation_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT,
                    role TEXT,
                    content TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS watchers (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    watcher_id TEXT,
                    result_hash TEXT,
                    sent_at TEXT,
                    PRIMARY KEY (watcher_id, result_hash)
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT,
                    detail TEXT,
                    created_at TEXT
                );
                """
            )

    # -- offsets --------------------------------------------------------

    def get_offset(self, transport: str = "telegram") -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT offset FROM offsets WHERE transport = ?", (transport,)
            ).fetchone()
            return int(row["offset"]) if row else 0

    def set_offset(self, offset: int, transport: str = "telegram") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO offsets (transport, offset, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(transport) DO UPDATE SET offset=excluded.offset, updated_at=excluded.updated_at",
                (transport, offset, _now()),
            )

    # -- conversation log -------------------------------------------------

    def log_message(self, chat_id: Any, role: str, content: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversation_log (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (str(chat_id), role, content, _now()),
            )

    def recent_conversation(self, chat_id: Any, limit: int = 10) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM conversation_log "
                "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (str(chat_id), limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    # -- watchers ---------------------------------------------------------

    def save_watcher(self, watcher_id: str, data: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO watchers (id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                (watcher_id, json.dumps(data, default=str), _now()),
            )

    def get_watcher(self, watcher_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT data FROM watchers WHERE id = ?", (watcher_id,)).fetchone()
            return json.loads(row["data"]) if row else None

    def list_watchers(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT data FROM watchers ORDER BY updated_at DESC").fetchall()
            return [json.loads(r["data"]) for r in rows]

    def delete_watcher(self, watcher_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM watchers WHERE id = ?", (watcher_id,))

    # -- approvals ----------------------------------------------------------

    def save_approval(self, approval_id: str, data: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO approvals (approval_id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(approval_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                (approval_id, json.dumps(data, default=str), _now()),
            )

    def get_approval(self, approval_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            return json.loads(row["data"]) if row else None

    def list_approvals(self, status: str | None = None) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT data FROM approvals ORDER BY updated_at DESC").fetchall()
            items = [json.loads(r["data"]) for r in rows]
            if status:
                items = [i for i in items if i.get("status") == status]
            return items

    # -- notifications (hash-based dedup) ------------------------------------

    def has_notified(self, watcher_id: str, result_hash: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM notifications WHERE watcher_id = ? AND result_hash = ?",
                (watcher_id, result_hash),
            ).fetchone()
            return row is not None

    def mark_notified(self, watcher_id: str, result_hash: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO notifications (watcher_id, result_hash, sent_at) VALUES (?, ?, ?)",
                (watcher_id, result_hash, _now()),
            )

    # -- audit log ------------------------------------------------------------

    def audit(self, event: str, detail: dict | str | None = None) -> None:
        if isinstance(detail, dict):
            detail_str = json.dumps(detail, default=str)
        else:
            detail_str = detail or ""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO audit_log (event, detail, created_at) VALUES (?, ?, ?)",
                (event, detail_str, _now()),
            )

    def recent_audit(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT event, detail, created_at FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]


_instances: dict[str, ResidentState] = {}


def get_state(db_path: str | Path) -> ResidentState:
    """Return a cached ResidentState for a given db path (per-process)."""
    key = str(db_path)
    if key not in _instances:
        _instances[key] = ResidentState(db_path)
    return _instances[key]
