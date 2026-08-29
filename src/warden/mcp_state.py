"""Durable storage for MCP registrations, approvals, and token metadata.

The MCP edge is a stateless HTTP process.  In cloud-primary mode its
identity documents live in the same Cloud SQL authority as Brain memory;
local JSON files are retained only for the local/offline server.
"""
from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any

_LOCK = Lock()
_SCHEMA_READY = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS warden_mcp_state (
    state_key TEXT PRIMARY KEY,
    document JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class MCPStateUnavailable(RuntimeError):
    """The configured durable MCP identity store cannot be reached."""


def cloud_state_enabled() -> bool:
    configured = os.getenv("WARDEN_MCP_STATE_BACKEND", "").strip().lower()
    if configured:
        return configured in {"postgres", "cloud", "cloud-primary"}
    return os.getenv("WARDEN_BRAIN_BACKEND", "local").strip().lower() in {
        "postgres", "cloud", "cloud-primary"
    }


def _dsn() -> str:
    return (os.getenv("WARDEN_BRAIN_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def _connect():
    dsn = _dsn()
    if not dsn:
        raise MCPStateUnavailable("WARDEN_BRAIN_DATABASE_URL/DATABASE_URL is not configured")
    try:
        import psycopg
    except ImportError as exc:
        raise MCPStateUnavailable("Install the cloud extra to use durable MCP state") from exc
    try:
        return psycopg.connect(dsn)
    except Exception as exc:
        raise MCPStateUnavailable(f"MCP state database connection failed: {exc}") from exc


def _ensure_schema(conn: Any) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()
    _SCHEMA_READY = True


def load_document(key: str) -> Any | None:
    """Load one JSON document, failing closed when cloud mode is unavailable."""
    if not cloud_state_enabled():
        return None
    with _LOCK:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT document FROM warden_mcp_state WHERE state_key = %s", (key,))
                row = cur.fetchone()
            return row[0] if row else None


def save_document(key: str, document: Any) -> None:
    """Atomically replace one JSON document in the Cloud SQL authority."""
    if not cloud_state_enabled():
        return
    encoded = json.dumps(document, sort_keys=True)
    with _LOCK:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO warden_mcp_state (state_key, document, updated_at)
                       VALUES (%s, %s::jsonb, now())
                       ON CONFLICT (state_key) DO UPDATE SET
                         document = EXCLUDED.document, updated_at = now()""",
                    (key, encoded),
                )
            conn.commit()


def durable_state_status() -> dict[str, Any]:
    """Return redacted readiness information for health/proof tooling."""
    status = {"backend": "postgres" if cloud_state_enabled() else "local", "ready": False}
    if not cloud_state_enabled():
        status["ready"] = True
        return status
    try:
        with _connect() as conn:
            _ensure_schema(conn)
        status["ready"] = True
    except Exception as exc:
        status["error"] = str(exc)
    return status
