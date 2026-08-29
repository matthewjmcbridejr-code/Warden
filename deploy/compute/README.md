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
