# ADR 0001: Warden Cloud Brain and Hybrid Execution

- Status: accepted for the McServer migration
- Date: 2026-08-28
- Scope: Warden production control plane, Brain, MCP, missions, memory, artifacts, and execution

## Decision

Warden is a hybrid system with a cloud-primary control plane. GCP is the
canonical home for durable Brain memory, shared state, missions, events,
checkpoints, handoffs, proof records, agent/MCP identities, queues, and
artifact metadata. Vercel hosts the web console and remote mission view. The
desktop Warden Desk remains local-primary only for device-local capabilities:
browser, terminal, files, GUI, and other work that must use the operator's
machine.

The cloud boundary is explicit:

```text
Warden Desk (local Captain + device capabilities)
        | authenticated device relay / cache / outbox
        v
GCP Cloud Brain API + authenticated MCP edge + queue + workers
        |                         |
        v                         v
Cloud SQL (state)             GCS (artifacts, exports, hashes)
        ^
        |
Vercel console / remote mission view (UI only)
```

The Cloud Brain is not a Vercel function, a browser, or an agent personality.
It is a durable shared control plane. Agents and harnesses consume the same
contracts and are interchangeable clients; they do not receive trust
authority merely by being an agent.

## Service placement

### GCP

- Cloud SQL PostgreSQL is the authoritative store for structured memory and,
  as migrations land, missions, events, checkpoints, handoffs, proof gates,
  identities, queues, and run metadata.
- GCS is the durable artifact/export store. Objects carry content hashes and
  retention/lifecycle policy; mutable local paths are never the artifact
  authority.
- An always-on authenticated MCP edge exposes the existing Warden MCP tool
  surface, OAuth/device authentication, client registration, and upstream hub
  policy. It is a replaceable gateway, not a database.
- Cloud workers perform cloud-safe queued work. They do not receive arbitrary
  shell access or automatic proof-gate approval.
- Secret Manager/KMS and provider-specific secret stores hold credentials.
  Secrets are never placed in Brain records, GitHub, Vercel bundles, or
  ordinary logs.

### Vercel and GitHub

- GitHub is source control, review, and CI trigger ownership.
- Vercel hosts the static/interactive console and same-origin remote view.
- Vercel is not the durable Brain, worker runtime, queue, trust authority, or
  secret vault. The Cloud Run Brain API stays authenticated/private; a
  server-side authenticated bridge or approved identity-aware load balancer is
  required before the console can call it.

### Desktop

The Desk keeps local Captain orchestration and local device execution. Its
SQLite/JSON Workbench data becomes a cache/offline replica rather than the
canonical shared state. Cloud writes use an idempotent outbox with retry,
conflict/version checks, and visible failure state. No local cache is silently
promoted to authority during a cloud outage.

## Persistence and consistency

The first cloud-primary boundary is memory. With
`WARDEN_BRAIN_BACKEND=postgres`, the existing MCP/API memory tools write to
PostgreSQL and maintain a local cache for offline reads. A failed write is
recorded once in `cloud-outbox/`, keyed by a deterministic content hash, and
replayed by the migration/sync command. PostgreSQL upserts compare source
timestamps so stale retries cannot overwrite a newer record.

The same pattern is required for the remaining state families:

1. Write an event/record with an idempotency key and source version.
2. Commit to the cloud authority, or append one durable local outbox item.
3. Replay with bounded retries and observable failure counts.
4. Resolve conflicts by version/updated-at rules and preserve history.

Long-running workflows use an explicit queue and checkpoint model. A worker
lease can expire and be reclaimed; a retry cannot duplicate a mission effect.
Every externally meaningful result has a proof/evidence record and artifact
reference. Human approval remains a separate state transition.

## Migration boundary

`docs/architecture.md` describes the historical local-first design. This ADR
supersedes its deployment/storage decision for production migration without
rewriting history. The migration is staged: memory, artifacts, missions/events
and proofs, then connector/run-history state. Existing mature implementations
(`brain_mcp_server.py`, `mcp_hub.py`, OAuth/client registration, bootstrap,
Brain tools, board/tasks, handoffs, proofs, and gateways) remain the contract
surface while their backing stores move behind adapters.

`scripts/migrate_brain.py --dry-run` inventories local Workbench memory with a
count, duplicate check, content hash, explicit source/destination, and an
exclusion list for secrets. `--apply` requires an explicitly configured
PostgreSQL DSN; it never guesses a destination.

## Security and shutdown gate

All internet-reachable MCP/Brain endpoints require authentication and DNS
rebinding protection. No `allUsers` IAM shortcut, static GCP key, or public
personal Brain endpoint is acceptable. Execution lanes remain disabled until
their worker identity, allowlist, isolation, resource limits, and proof gates
are verified.

McServer is not stopped by this ADR. Shutdown requires successful live proofs
for memory write/recall, restart persistence, Desk-off access, cross-agent
sharing, project scoping, local and cloud mission paths, Needs You, failure
handling, artifact integrity, and rollback. Until then McServer remains the
rollback path and its data is retained read-only after cutover.
