# Warden cloud deployment

This is the migration boundary for moving Warden off McServer:

```text
GitHub (source + CI) -> Cloud Build -> Cloud Run (Python API)
GitHub (source) -> Vercel (static Warden UI + same-origin /api proxy)
Cloud Run -> Secret Manager, Cloud SQL, Cloud Storage, Vertex AI Search
```

The legacy service is not safe to scale as-is. It writes SQLite/JSON files to
the local filesystem and contains local subprocess/tmux lanes. Cloud Run's
filesystem is ephemeral, so the production service starts read-only with all
runner flags disabled. Cloud SQL/GCS adapters must be enabled before turning on
production writes or multi-instance scaling.

## Canonical storage and migration boundary

The accepted placement decision is recorded in
[`docs/adr/0001-warden-cloud-brain-hybrid-execution.md`](adr/0001-warden-cloud-brain-hybrid-execution.md).
Cloud SQL is the durable Brain/state authority; GCS is the artifact/export
authority; Vercel is only the console; the e2-medium worker is an execution
plane; and the desktop is the local device plane. The local Workbench remains
available as a cache/offline replica with an idempotent outbox.

The first implemented adapter is memory. It is opt-in until the database is
provisioned:

```bash
python3 scripts/migrate_brain.py --dry-run
# After reviewing the report and provisioning the explicitly named database:
WARDEN_BRAIN_BACKEND=postgres \
WARDEN_BRAIN_DATABASE_URL='postgresql://...' \
python3 scripts/migrate_brain.py --apply
```

Do not put the DSN in GitHub or a Vercel bundle. Inject it from Secret Manager
into the authenticated GCP service and into an approved operator migration
session. If the cloud is temporarily unreachable, the memory adapter writes
one deterministic item per change under `cloud-outbox/`; replay with:

```bash
WARDEN_BRAIN_BACKEND=postgres \
WARDEN_BRAIN_DATABASE_URL='postgresql://...' \
python3 scripts/migrate_brain.py --replay-outbox
```

The SQL bootstrap is [`deploy/cloudsql/001_brain_memories.sql`](../deploy/cloudsql/001_brain_memories.sql).
The control-plane tables are bootstrapped alongside it by the API and are also
included in [`deploy/cloudsql/001_brain_memories.sql`](../deploy/cloudsql/001_brain_memories.sql).
They hold mission plans, run/evidence/proof records, ordered chat events,
conversations, and worker leases as JSONB records with idempotent keys.

To inventory and then migrate existing local control state (including Captain
plans, workbench records, run history, proof gates, and the local group chat),
use the separate migration boundary below. It never reads connector/vault
directories or secret-looking files and redacts text fields before a write:

```bash
python3 scripts/migrate_control_state.py --dry-run
WARDEN_BRAIN_BACKEND=postgres \
WARDEN_BRAIN_DATABASE_URL='postgresql://...' \
python3 scripts/migrate_control_state.py --apply
```

The migration is safe to rerun: existing record IDs are upserted and chat
events use their existing idempotency keys. Artifact file contents are not
copied by this command; artifact promotion to GCS is a separate, hash-checked
operation. Connector credentials are intentionally excluded and must be
re-issued through Secret Manager/approved connector flows.

## Always-on MCP edge

The existing `python -m warden.brain_mcp_server --http --host ... --port 8126`
is the MCP edge contract. Deploy it as an authenticated, independently
replaceable GCP service (dedicated hardened Compute Engine gateway or a
private Cloud Run service behind an approved authenticated ingress). Keep the
OAuth/client-registration state durable and keep the endpoint protected by
OAuth 2.1/device auth or scoped bearer tokens. Do not expose the personal
Brain anonymously and do not use `allUsers` when the organization policy
rejects it. DNS and OAuth redirect changes require an explicit domain cutover.

The current `warden-worker` e2-medium is the execution plane, not the durable
database or trust authority. Its runner flags remain disabled until worker
identity, allowlists, isolation, queue leases, and proof-gate behavior have
live evidence.

## Durable mission queue

Cloud Run publishes bounded Captain-step envelopes to the `warden-missions`
Pub/Sub topic when the local runner is unavailable. The e2-medium consumes the
`warden-worker-missions` subscription, records a Cloud SQL mission receipt, and
uses a Cloud SQL lease keyed by mission ID before acknowledging the message.
`WARDEN_WORKER_EXECUTION_ENABLED` remains false by default; receiving a queued
mission is not permission to interpret arbitrary message text as a shell
command. The dead-letter topic is the recovery path for repeated delivery
failures.

The Cloud Run runtime service account needs only `roles/pubsub.publisher` on
the topic, and the worker identity needs only `roles/pubsub.subscriber` on the
subscription. No service-account key is needed.

## Vercel console authentication gate

The server-side bridge requires the encrypted Vercel production variable
`WARDEN_CONSOLE_TOKEN` and the `X-Warden-Console-Token` header. Anonymous
requests return `401`; the token is not bundled into the static UI. This is a
temporary fail-closed gate for operator proofs, not a substitute for end-user
identity. Before general use, register a Sign in with Vercel OAuth integration
or enable approved Vercel deployment protection, then replace the temporary
header gate with verified user sessions. Do not put the token in frontend
JavaScript, GitHub, or a URL.

## One-time GCP setup

Run from the repository root with the intended GCP project selected:

```bash
gcloud config set project booming-key-500220-d9
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  sqladmin.googleapis.com storage.googleapis.com discoveryengine.googleapis.com
gcloud artifacts repositories create warden --repository-format=docker \
  --location=us-central1 --description='Warden Cloud Run images'
gcloud secrets create OPENROUTER_API_KEY --replication-policy=automatic
gcloud secrets create WARDEN_CONNECTOR_ENCRYPTION_KEY --replication-policy=automatic
```

Add secret values through an approved secret-injection workflow. Do not put
them in GitHub, Vercel, a Dockerfile, or a shell history.

## Deploy the API

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_SERVICE=warden-api,_REGION=us-central1
gcloud run services describe warden-api --region=us-central1 \
  --format='value(status.url)'
```

Copy the resulting Cloud Run URL into the `destination` in `vercel.json`,
replacing `warden-api-REPLACE_ME-uc.a.run.app`, and commit that change. The
service is private by default. Before the Vercel UI can call it, add an
authenticated Vercel-to-GCP bridge (for example a Vercel server-side proxy
using workload identity federation) or use an approved identity-aware load
balancer. Do not make the personal Brain API public as a shortcut.

## Connect GitHub and Vercel

1. Import `matthewjmcbridejr-code/Warden` into the linked Vercel project.
2. Set the Vercel root directory to the repository root and leave the output
   directory empty; the UI is already static under `web/warden`.
3. Vercel should create preview deployments for pull requests and production
   deployments from the chosen release branch.
4. Configure the GitHub repository's Cloud Build trigger for the same release
   branch using `cloudbuild.yaml`.

## Cutover checklist

Do not stop McServer until all of these are true:

- `https://<vercel-domain>/api/mcharness/health` returns healthy.
- Brain data has been exported to the approved GCS bucket and indexed in
  Vertex AI Search.
- Run history, connector tokens, proof artifacts, and workbench state have
  Cloud SQL/GCS implementations; local SQLite/JSON is no longer authoritative.
- OAuth redirect URIs use the Vercel domain and secrets are in Secret Manager.
- A production preview passes the smoke tests and a rollback deployment is
  known.

After that proof, disable the McServer systemd units and retain a read-only
backup for the agreed retention period. Deletion is a separate, explicit
operation.
