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
