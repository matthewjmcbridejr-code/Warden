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
replacing `warden-api-REPLACE_ME-uc.a.run.app`, and commit that change.

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
