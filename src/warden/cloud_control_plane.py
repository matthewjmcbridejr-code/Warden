"""Cloud-primary records, ordered events, and worker leases.

This adapter deliberately stores validated Warden payloads as JSONB. Existing
Python models remain the contract surface while their authority moves from
local JSON/SQLite files to Cloud SQL. Local callers can continue to maintain a
cache and enqueue an idempotent outbox item when the cloud is unavailable.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from .cloud_brain import _Outbox

CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS warden_control_records (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (record_type, record_id)
);
CREATE INDEX IF NOT EXISTS warden_control_records_type_idx
    ON warden_control_records (record_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS warden_control_streams (
    stream_id TEXT PRIMARY KEY,
    last_seq BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS warden_control_events (
    event_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    seq BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (stream_id, seq)
);
CREATE INDEX IF NOT EXISTS warden_control_events_stream_idx
    ON warden_control_events (stream_id, seq);

CREATE TABLE IF NOT EXISTS warden_control_leases (
    lease_key TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

RECORD_UPSERT_SQL = """INSERT INTO warden_control_records
    (record_type, record_id, payload, source_updated_at, updated_at)
    VALUES (%s, %s, %s::jsonb, %s, now())
    ON CONFLICT (record_type, record_id) DO UPDATE SET
      payload = EXCLUDED.payload,
      source_updated_at = EXCLUDED.source_updated_at,
      updated_at = now()
    WHERE warden_control_records.source_updated_at <= EXCLUDED.source_updated_at"""


class CloudControlUnavailable(RuntimeError):
    """Cloud SQL control-plane storage is unavailable."""


def cloud_control_enabled() -> bool:
    return os.getenv("WARDEN_BRAIN_BACKEND", "local").strip().lower() in {
        "postgres", "cloud", "cloud-primary"
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _now()


class CloudControlPlane:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = (dsn or os.getenv("WARDEN_BRAIN_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()

    def _connect(self):
        if not self.dsn:
            raise CloudControlUnavailable("WARDEN_BRAIN_DATABASE_URL/DATABASE_URL is not configured")
        try:
            import psycopg
        except ImportError as exc:
            raise CloudControlUnavailable("Install the cloud extra to use PostgreSQL control state") from exc
        try:
            return psycopg.connect(self.dsn)
        except Exception as exc:
            raise CloudControlUnavailable(f"Control-plane database connection failed: {exc}") from exc

    @staticmethod
    def ensure_schema_on(conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute(CONTROL_SCHEMA)
        conn.commit()

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            self.ensure_schema_on(conn)

    def upsert_record(
        self,
        record_type: str,
        record_id: str,
        payload: dict[str, Any],
        *,
        source_updated_at: Any = None,
    ) -> None:
        encoded = json.dumps(payload, sort_keys=True, default=str)
        with self._connect() as conn:
            self.ensure_schema_on(conn)
            with conn.cursor() as cur:
                cur.execute(
                    RECORD_UPSERT_SQL,
                    (record_type, record_id, encoded, _as_datetime(source_updated_at or payload.get("updated_at"))),
                )
            conn.commit()

    def get_record(self, record_type: str, record_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            self.ensure_schema_on(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM warden_control_records WHERE record_type = %s AND record_id = %s",
                    (record_type, record_id),
                )
                row = cur.fetchone()
            return row[0] if row else None

    def list_records(self, record_type: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self.ensure_schema_on(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT payload FROM warden_control_records
                       WHERE record_type = %s ORDER BY updated_at DESC LIMIT %s""",
                    (record_type, max(1, min(int(limit), 1000))),
                )
                rows = cur.fetchall()
            return [row[0] for row in rows]

    def append_event(
        self,
        stream_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        with self._connect() as conn:
            self.ensure_schema_on(conn)
            with conn.cursor() as cur:
                if idempotency_key:
                    cur.execute(
                        "SELECT payload FROM warden_control_events WHERE idempotency_key = %s",
                        (idempotency_key,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        return existing[0], False
                cur.execute(
                    "INSERT INTO warden_control_streams (stream_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (stream_id,),
                )
                cur.execute(
                    "SELECT last_seq FROM warden_control_streams WHERE stream_id = %s FOR UPDATE",
                    (stream_id,),
                )
                seq = int(cur.fetchone()[0]) + 1
                stored = dict(payload)
                stored["event_id"] = event_id
                stored["seq"] = seq
                stored["stream_id"] = stream_id
                stored["event_type"] = event_type
                cur.execute(
                    """INSERT INTO warden_control_events
                       (event_id, stream_id, seq, event_type, idempotency_key, payload)
                       VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
                    (event_id, stream_id, seq, event_type, idempotency_key, json.dumps(stored, default=str)),
                )
                cur.execute(
                    "UPDATE warden_control_streams SET last_seq = %s WHERE stream_id = %s",
                    (seq, stream_id),
                )
            conn.commit()
            return stored, True

    def list_events(self, stream_id: str, *, since_seq: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self.ensure_schema_on(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT payload FROM warden_control_events
                       WHERE stream_id = %s AND seq > %s ORDER BY seq ASC LIMIT %s""",
                    (stream_id, max(0, int(since_seq)), max(1, min(int(limit), 1000))),
                )
                return [row[0] for row in cur.fetchall()]

    def get_event_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            self.ensure_schema_on(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM warden_control_events WHERE idempotency_key = %s",
                    (idempotency_key,),
                )
                row = cur.fetchone()
            return row[0] if row else None

    def enqueue_record(self, record_type: str, record_id: str, payload: dict[str, Any]) -> None:
        _Outbox().enqueue(
            "upsert_control_record",
            {"record_type": record_type, "record_id": record_id, "payload": payload},
        )

    def enqueue_event(self, stream_id: str, event_type: str, payload: dict[str, Any], *, event_id: str, idempotency_key: str | None = None) -> None:
        _Outbox().enqueue(
            "append_control_event",
            {
                "stream_id": stream_id,
                "event_type": event_type,
                "payload": payload,
                "event_id": event_id,
                "idempotency_key": idempotency_key,
            },
        )

    def acquire_lease(self, lease_key: str, owner_id: str, *, ttl_seconds: int = 60) -> bool:
        now = _now()
        expires = now.timestamp() + max(1, int(ttl_seconds))
        with self._connect() as conn:
            self.ensure_schema_on(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO warden_control_leases (lease_key, owner_id, expires_at)
                       VALUES (%s, %s, to_timestamp(%s))
                       ON CONFLICT (lease_key) DO UPDATE SET
                         owner_id = EXCLUDED.owner_id, expires_at = EXCLUDED.expires_at, updated_at = now()
                       WHERE warden_control_leases.expires_at <= %s OR warden_control_leases.owner_id = %s
                       RETURNING owner_id""",
                    (lease_key, owner_id, expires, now, owner_id),
                )
                acquired = cur.fetchone() is not None
            conn.commit()
            return acquired

    def release_lease(self, lease_key: str, owner_id: str) -> bool:
        with self._connect() as conn:
            self.ensure_schema_on(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM warden_control_leases WHERE lease_key = %s AND owner_id = %s",
                    (lease_key, owner_id),
                )
                released = cur.rowcount > 0
            conn.commit()
            return released
