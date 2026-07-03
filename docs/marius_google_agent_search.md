# Marius-Brain: Google Agent Search Foundation

Marius-Brain is the giant searchable memory layer for Marius, Warden, and GradeMy. It uses Google Agent Search (Vertex AI Search / Discovery Engine) as the backend for large-scale document and project-context recall.

## Current Setup Status (proven)
- **Google Project**: `project-b11857c2-0ddb-4154-802` (McProject)
- **Billing Account**: `01C341-7C5C1D-7452A3` (Google Credit Billing Account)
- **GCS Bucket**: `gs://marius-brain-292003335586`
- **Location**: `global`
- **APIs Enabled**: Discovery Engine, Storage, AI Platform.

## Setup Steps

### 1. Verification
Run the doctor script to check your local and cloud state:
```bash
bash scripts/google_agent_search_doctor.sh
```

### 2. Authentication
ADC is required. If missing, run:
```bash
gcloud auth application-default login --no-launch-browser
```

### 3. Local Export
Generate a safe JSONL export of your project context:
```text
/search export warden
```
This generates a file in `~/.local/share/marius/brain/exports/warden.jsonl`.

### 4. Cloud Foundation
Setup GCS bucket and upload exports:
```bash
bash scripts/marius_brain_gcs_setup.sh
```

### 5. Discovery Engine Configuration
Currently, infrastructure creation via API is manual or requires setup scripts. Captured resources:
- **Data Store ID**: `marius-brain-warden`
- **Engine ID**: `marius-brain`
- **Serving Config**: `default_config`

Use the setup helper for dry-run or creation:
```bash
.venv/bin/python scripts/marius_brain_discovery_setup.py --create
```

## Secret Exclusion Policy
The following are NEVER indexed:
- `.env` files
- Private keys (`.pem`, `.key`, `id_rsa`)
- Files containing strings like `API_KEY`, `SECRET`, `TOKEN`.
- Folders like `.git`, `.venv`, `node_modules`.

## Provider Configuration
Configure the active search provider via environment variables:
- `MARIUS_SEARCH_PROVIDER=local|google`
- `GOOGLE_CLOUD_PROJECT=project-b11857c2-0ddb-4154-802`
- `GOOGLE_AGENT_SEARCH_ENGINE_ID=marius-brain`

## Troubleshooting
- **ADC Missing**: Re-run the login command.
- **Search Error**: Ensure the Engine ID exists in the Google Cloud Console under AI Applications -> Agent Search.
- **Permission Denied**: Check IAM roles for the authenticated account.
