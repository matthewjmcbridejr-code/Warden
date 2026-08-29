"""Cloud-primary memory storage with an offline local cache and outbox.

Setting ``WARDEN_BRAIN_BACKEND=postgres`` makes PostgreSQL authoritative for
memories. The local WorkbenchStore under ``cloud-cache`` is then only a cache
and offline fallback. Failed writes are recorded in an idempotent outbox and
can be replayed by ``scripts/migrate_brain.py --replay-outbox``.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .paths import data_root

SCHEMA = """
CREATE TABLE IF NOT EXISTS warden_brain_memories (
    memory_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    project_id TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT,
    summary TEXT NOT NULL,
    search_text TEXT NOT NULL,
    record JSONB NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS warden_brain_memories_project_idx ON warden_brain_memories (project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS warden_brain_memories_scope_idx ON warden_brain_memories (scope, updated_at DESC);
CREATE INDEX IF NOT EXISTS warden_brain_memories_status_idx ON warden_brain_memories (status, updated_at DESC);
"""

UPSERT_SQL = """INSERT INTO warden_brain_memories
    (memory_id, scope, project_id, kind, status, title, summary,
     search_text, record, source_updated_at, updated_at)
    VALUES (%(memory_id)s, %(scope)s, %(project_id)s, %(kind)s,
            %(status)s, %(title)s, %(summary)s, %(search_text)s,
            %(record)s::jsonb, %(source_updated_at)s, now())
    ON CONFLICT (memory_id) DO UPDATE SET
      scope=EXCLUDED.scope, project_id=EXCLUDED.project_id,
      kind=EXCLUDED.kind, status=EXCLUDED.status,
      title=EXCLUDED.title, summary=EXCLUDED.summary,
      search_text=EXCLUDED.search_text, record=EXCLUDED.record,
      source_updated_at=EXCLUDED.source_updated_at, updated_at=now()
    WHERE warden_brain_memories.source_updated_at <= EXCLUDED.source_updated_at"""


class CloudBrainUnavailable(RuntimeError):
    """The configured cloud backend cannot be reached or is not configured."""


def backend_name() -> str:
    return os.getenv("WARDEN_BRAIN_BACKEND", "local").strip().lower() or "local"


def is_cloud_primary() -> bool:
    return backend_name() in {"postgres", "cloud", "cloud-primary"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _cache_store():
    from .workbench import WorkbenchStore

    return WorkbenchStore(data_root() / "cloud-cache" / "workbench")


class _Outbox:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = (root or data_root() / "cloud-outbox").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def enqueue(self, operation: str, payload: dict[str, Any]) -> Path:
        body = {"operation": operation, "payload": payload}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:24]
        path = self.root / f"{digest}.json"
        if not path.exists():
            tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps(body, indent=2, sort_keys=True, default=_jsonable) + "\n", encoding="utf-8")
            tmp.replace(path)
        return path

    def pending(self) -> list[Path]:
        return sorted(self.root.glob("*.json"))


class PostgresBrain:
    """Postgres adapter for the canonical memory record set."""

    def __init__(self, dsn: Optional[str] = None) -> None:
        self.dsn = (dsn or os.getenv("WARDEN_BRAIN_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
        self.outbox = _Outbox()

    def _connect(self):
        if not self.dsn:
            raise CloudBrainUnavailable("WARDEN_BRAIN_DATABASE_URL/DATABASE_URL is not configured")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise CloudBrainUnavailable("Install the cloud extra to use PostgreSQL: pip install 'mcharness[cloud]'") from exc
        try:
            return psycopg.connect(self.dsn, row_factory=dict_row)
        except Exception as exc:
            raise CloudBrainUnavailable(f"PostgreSQL connection failed: {exc}") from exc

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)
            conn.commit()

    @staticmethod
    def _record_payload(memory: Any) -> dict[str, Any]:
        return memory.model_dump(mode="json")

    @staticmethod
    def _search_text(memory: Any) -> str:
        values: list[str] = []
        for value in PostgresBrain._record_payload(memory).values():
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, list):
                values.extend(str(item) for item in value)
            elif isinstance(value, dict):
                values.extend(str(item) for item in value.values())
        return " ".join(values).lower()

    def upsert(self, memory: Any) -> None:
        record = self._record_payload(memory)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(UPSERT_SQL, self._parameters(memory, record))
                conn.commit()
        except CloudBrainUnavailable:
            self.outbox.enqueue("upsert_memory", record)
            raise
        except Exception as exc:
            self.outbox.enqueue("upsert_memory", record)
            raise CloudBrainUnavailable(f"PostgreSQL memory write failed: {exc}") from exc

    def _parameters(self, memory: Any, record: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        record = record or self._record_payload(memory)
        return {
            "memory_id": memory.memory_id,
            "scope": memory.scope,
            "project_id": memory.project_id,
            "kind": memory.kind,
            "status": memory.status,
            "title": memory.title,
            "summary": memory.summary,
            "search_text": self._search_text(memory),
            "record": json.dumps(record),
            "source_updated_at": memory.updated_at,
        }

    def upsert_many(self, memories: list[Any]) -> int:
        """Upsert a migration batch in one transaction."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    for memory in memories:
                        cur.execute(UPSERT_SQL, self._parameters(memory))
                conn.commit()
            return len(memories)
        except CloudBrainUnavailable:
            for memory in memories:
                self.outbox.enqueue("upsert_memory", self._record_payload(memory))
            raise
        except Exception as exc:
            for memory in memories:
                self.outbox.enqueue("upsert_memory", self._record_payload(memory))
            raise CloudBrainUnavailable(f"PostgreSQL batch write failed: {exc}") from exc

    def _rows(self, query: str, params: tuple[Any, ...]) -> list[Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return list(cur.fetchall())

    def list_memories(self) -> list[Any]:
        from .workbench import WorkbenchMemory

        rows = self._rows(
            "SELECT record FROM warden_brain_memories WHERE status <> 'forgotten' ORDER BY updated_at DESC",
            (),
        )
        return [WorkbenchMemory.model_validate(row["record"]) for row in rows]

    def search_memories(self, query: str, *, scope: Optional[str] = None, limit: int = 20) -> list[Any]:
        from .workbench import WorkbenchMemory

        terms = [term for term in query.strip().lower().split() if len(term) > 1]
        clauses = ["status <> 'forgotten'"]
        params: list[Any] = []
        if scope:
            clauses.append("lower(scope) = lower(%s)")
            params.append(scope.strip())
        for term in terms:
            clauses.append("search_text LIKE %s")
            params.append(f"%{term}%")
        params.append(max(1, min(int(limit), 100)))
        rows = self._rows(
            f"SELECT record FROM warden_brain_memories WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT %s",
            tuple(params),
        )
        return [WorkbenchMemory.model_validate(row["record"]) for row in rows]

    def get_memory(self, memory_id: str) -> Any:
        from .workbench import WorkbenchMemory

        rows = self._rows("SELECT record FROM warden_brain_memories WHERE memory_id = %s", (memory_id,))
        if not rows:
            raise KeyError(f"memory not available: {memory_id}")
        return WorkbenchMemory.model_validate(rows[0]["record"])


class CloudPrimaryMemoryStore:
    """Workbench-compatible memory facade used by MCP/API memory paths."""

    def __init__(self, local_store: Any) -> None:
        self.local = local_store
        self.cloud = PostgresBrain()
        self.outbox = _Outbox()

    def list_memories(self) -> list[Any]:
        try:
            memories = self.cloud.list_memories()
            for memory in memories:
                self._cache_memory(memory)
            return memories
        except CloudBrainUnavailable:
            return self.local.list_memories()

    def search_memories(self, query: str, *, scope: Optional[str] = None, limit: int = 20) -> list[Any]:
        try:
            memories = self.cloud.search_memories(query, scope=scope, limit=limit)
            for memory in memories:
                self._cache_memory(memory)
            return memories
        except CloudBrainUnavailable:
            return self.local.search_memories(query, scope=scope, limit=limit)

    def get_memory(self, memory_id: str) -> Any:
        try:
            memory = self.cloud.get_memory(memory_id)
            self._cache_memory(memory)
            return memory
        except CloudBrainUnavailable:
            return self.local.get_memory(memory_id)

    def update_memory_promotion(self, memory_id: str, **kwargs: Any) -> Any:
        memory = self.get_memory(memory_id)
        if kwargs.get("status") is not None:
            memory.status = kwargs["status"]
        if kwargs.get("source_ref") is not None:
            memory.source_ref = kwargs["source_ref"]
        memory.updated_at = datetime.now(timezone.utc)
        self._cache_memory(memory)
        try:
            self.cloud.upsert(memory)
        except CloudBrainUnavailable:
            self.outbox.enqueue("upsert_memory", memory.model_dump(mode="json"))
        return memory

    def save_memory(self, memory: Any) -> Any:
        """Persist a validated memory to cache and authoritative cloud storage."""
        self._cache_memory(memory)
        try:
            self.cloud.upsert(memory)
        except CloudBrainUnavailable:
            self.outbox.enqueue("upsert_memory", memory.model_dump(mode="json"))
        return memory

    def build_memory_context_pack(self, **kwargs: Any) -> dict[str, Any]:
        try:
            self.list_memories()
        except Exception:
            pass
        return self.local.build_memory_context_pack(**kwargs)

    def remember_memory(self, payload: Any) -> Any:
        memory = self.local.remember_memory(payload)
        try:
            self.cloud.upsert(memory)
        except CloudBrainUnavailable:
            self.outbox.enqueue("upsert_memory", memory.model_dump(mode="json"))
        return memory

    def create_memory(self, payload: Any) -> Any:
        from .workbench import WorkbenchMemoryRememberRequest

        return self.remember_memory(
            WorkbenchMemoryRememberRequest(
                memory_id=payload.memory_id,
                scope=payload.scope,
                content=payload.summary,
                source=payload.source,
                title=payload.title,
                source_ref=payload.source_ref,
                tags=payload.tags,
                kind=payload.kind,
                status=payload.status,
                confidence=payload.confidence,
                project_id=payload.project_id,
                repo_path=payload.repo_path,
                branch=payload.branch,
                task_id=payload.task_id,
                agent_id=payload.agent_id,
                metadata=payload.metadata,
                compacted=payload.compacted,
                notes=payload.notes,
            )
        )

    def _cache_memory(self, memory: Any) -> None:
        path = self.local._path("memories", memory.memory_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(memory.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.local, name)


_STORE: Any = None


def get_memory_store(local_store: Any = None) -> Any:
    global _STORE
    if not is_cloud_primary():
        if local_store is not None:
            return local_store
        from .workbench import WorkbenchStore

        return WorkbenchStore()
    if _STORE is None:
        if local_store is None:
            local_store = _cache_store()
        _STORE = CloudPrimaryMemoryStore(local_store)
    return _STORE


def cloud_brain_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "backend": backend_name(),
        "cloud_primary": is_cloud_primary(),
        "outbox_pending": len(_Outbox().pending()),
    }
    if is_cloud_primary():
        try:
            PostgresBrain().ensure_schema()
            status["postgres"] = "reachable"
        except Exception as exc:
            status["postgres"] = "unavailable"
            status["error"] = str(exc)
    return status


def replay_outbox(*, limit: int = 100) -> dict[str, Any]:
    brain = PostgresBrain()
    pending = _Outbox().pending()[: max(1, min(limit, 1000))]
    replayed = 0
    failed: list[dict[str, str]] = []
    for path in pending:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            if body.get("operation") != "upsert_memory":
                raise ValueError(f"unsupported operation: {body.get('operation')}")
            from .workbench import WorkbenchMemory

            brain.upsert(WorkbenchMemory.model_validate(body["payload"]))
            path.unlink()
            replayed += 1
        except Exception as exc:
            failed.append({"path": str(path), "error": str(exc)})
    return {"pending_before": len(pending), "replayed": replayed, "failed": failed, "remaining": len(_Outbox().pending())}
