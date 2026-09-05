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

-- OAuth/client-registration documents for the authenticated MCP edge. The
-- edge is otherwise stateless; these documents must survive replacement.
CREATE TABLE IF NOT EXISTS warden_mcp_state (
    state_key TEXT PRIMARY KEY,
    document JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cloud-primary mission/control records, ordered event streams, and worker
-- leases. Payloads remain the existing Warden contract models as JSONB.
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
