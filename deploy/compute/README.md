# Warden e2-medium worker

The worker VM runs the production branch from GitHub and owns the parts of
Warden that require a normal Linux host: Git worktrees, subprocesses, tmux,
and supervised agent runners. It is not the public web endpoint.

Create it in GCP with:

```bash
gcloud compute instances create warden-worker \
  --project=booming-key-500220-d9 \
  --zone=us-central1-c \
  --machine-type=e2-medium \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-balanced \
  --scopes=https://www.googleapis.com/auth/cloud-platform \
  --metadata-from-file=startup-script=deploy/compute/warden-worker-startup.sh \
  --tags=warden-worker
```

The worker is intentionally bound to `127.0.0.1:8125`; expose it only through
an authenticated internal path when the worker protocol is finalized. Do not
open port 8125 to the internet.

## Dedicated MCP edge

`warden-mcp-edge-startup.sh` provisions a separate always-on gateway. It uses
the Cloud SQL Auth Proxy for the Brain database, stores MCP OAuth/client state
in Cloud SQL, and sets `WARDEN_MCP_HUB_ENABLED=false`, so it has no runtime
dependency on McServer. It does not change DNS or stop McServer.

Create the operator passphrase secret, allow the VM service account to read the
two required secrets, then provision the edge:

```bash
gcloud secrets create MCP_OAUTH_OWNER_PASSPHRASE --replication-policy=automatic
openssl rand -base64 36 | gcloud secrets versions add MCP_OAUTH_OWNER_PASSPHRASE --data-file=-
gcloud projects add-iam-policy-binding booming-key-500220-d9 \
  --member=serviceAccount:341941245324-compute@developer.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
gcloud compute firewall-rules create warden-mcp-edge-web \
  --network=default --target-tags=warden-mcp-edge --allow=tcp:80,tcp:443
gcloud compute instances create warden-mcp-edge \
  --project=booming-key-500220-d9 --zone=us-central1-c --machine-type=e2-small \
  --tags=warden-mcp-edge --scopes=cloud-platform \
  --metadata=MCP_EDGE_DOMAIN=mcp.mctable.online \
  --metadata-from-file=startup-script=deploy/compute/warden-mcp-edge-startup.sh
```

After the VM is healthy, point the chosen MCP hostname's A record at its
external IP, wait for Caddy to obtain TLS, and only then update the OAuth
issuer/callback configuration. Keep the old DNS record and McServer available
until MCP, memory, restart, and rollback proofs pass.
