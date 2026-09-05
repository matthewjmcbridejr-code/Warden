# Warden capability expansion

Warden now exposes a client-neutral capability layer over MCP. Every
authenticated client still begins with `warden_bootstrap`; it can then call
`warden_capability_catalog` to discover product capabilities instead of
maintaining its own map of provider tools.

The catalog groups the live surface into shared context, coordination,
research and code, communication, bounded execution and artifacts, and shared
skills. Each group reports readiness, the tools currently exposed, the
resources it represents, and the policy boundary for writes and external side
effects. Credentials remain server-side.

`warden_client_health` gives a client one compact diagnostic view containing its
authenticated identity, bootstrap state, last tool activity for the current
process, Warden API and memory health, semantic-index readiness, capability
readiness, and the current tool-catalog revision.

`warden_skill_catalog` and `warden_skill_get` make Warden's built-in role
envelopes and local playbooks available as executable guidance. A role carries
its allowed and forbidden action classes, whether it can write or dispatch,
and the proof/approval boundary. This turns skill discovery into a bounded
capability contract while keeping the upstream public skill directory useful
for references and methodology.

Artifacts are now first-class MCP resources. Clients can use
`warden_artifact_store`, `warden_artifact_get`, and `warden_artifact_list`, or
read `warden://artifacts/<artifact_id>` directly. Artifact IDs are content
addressed and immutable. Local deployments persist content under the Warden
data root; cloud deployments use GCS when `WARDEN_ARTIFACT_BACKEND=gcs` and
`WARDEN_ARTIFACT_BUCKET` are configured.

The Brain has two explicit indexing operations:

- `brain_index_status` reports source and vector readiness.
- `brain_reindex_embeddings` backfills recent memory vectors in a bounded batch
  when the configured embedding backend is available.

The bulletin-board reader now uses the same data-root resolver as the task
lifecycle module. This keeps bootstrap coordination state aligned across local
and deployed processes instead of defaulting to a second, empty board path.

## Rollout checklist

1. Deploy the server changes and verify `warden_bootstrap`,
   `warden_capability_catalog`, and `warden_client_health` from each supported
   client registration.
2. Configure the embedding backend and run bounded batches of
   `brain_reindex_embeddings` until `brain_index_status.vector_count` is
   non-zero.
3. Set `WARDEN_ARTIFACT_BACKEND=gcs` and a bucket in Cloud Run when artifacts
   must survive instance replacement; local filesystem persistence is suitable
   for local Warden only.
4. Connect provider accounts at Warden, then verify their live health through
   `warden_service_catalog`; clients should never receive provider credentials.
5. Enable the Captain reconciliation loop after the shared board path is
   confirmed, and resolve any reported tool-surface drift by refreshing the
   MCP catalog revision.
