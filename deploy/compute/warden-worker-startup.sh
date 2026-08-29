#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/matthewjmcbridejr-code/Warden.git"
REPO_BRANCH="feat/mission-control-product-completion"
PROJECT_ID="booming-key-500220-d9"
INSTANCE_CONNECTION="${PROJECT_ID}:us-central1:warden-brain"
APP_DIR="/opt/warden"
DATA_DIR="/var/lib/warden"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git python3-venv python3-pip build-essential tmux

id -u warden >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/warden --shell /usr/sbin/nologin warden
mkdir -p "${APP_DIR}" "${DATA_DIR}"
chown -R warden:warden "${APP_DIR}" "${DATA_DIR}"

git_warden() {
  runuser -u warden -- git "$@"
}

if [ ! -d "${APP_DIR}/.git" ]; then
  git_warden clone --branch "${REPO_BRANCH}" --single-branch "${REPO_URL}" "${APP_DIR}"
else
  git_warden -C "${APP_DIR}" fetch origin "${REPO_BRANCH}"
  git_warden -C "${APP_DIR}" merge --ff-only "origin/${REPO_BRANCH}"
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install "${APP_DIR}[cloud]"
chown -R warden:warden "${APP_DIR}" "${DATA_DIR}"

metadata_token() {
  curl -fsS -H 'Metadata-Flavor: Google' \
    'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
}

secret_value() {
  local secret_name="$1"
  local access_token
  access_token="$(metadata_token)"
  curl -fsS -H "Authorization: Bearer ${access_token}" \
    "https://secretmanager.googleapis.com/v1/projects/${PROJECT_ID}/secrets/${secret_name}/versions/latest:access" \
    | python3 -c 'import base64,json,sys; print(base64.b64decode(json.load(sys.stdin)["payload"]["data"]).decode())'
}

RAW_DSN="$(secret_value WARDEN_BRAIN_DATABASE_URL)"
BRAIN_DSN="$(RAW_DSN="${RAW_DSN}" python3 -c 'import os; d=os.environ["RAW_DSN"]; print(d.replace("/cloudsql/booming-key-500220-d9:us-central1:warden-brain", "/run/warden-cloudsql/booming-key-500220-d9:us-central1:warden-brain"))')"
umask 077
printf '%s\n' "WARDEN_BRAIN_DATABASE_URL=${BRAIN_DSN}" > /etc/warden-worker.env
chown root:warden /etc/warden-worker.env
chmod 0640 /etc/warden-worker.env
unset RAW_DSN BRAIN_DSN

if [ ! -x /usr/local/bin/cloud-sql-proxy ]; then
  curl -fsSL --retry 5 -o /usr/local/bin/cloud-sql-proxy \
    https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.25.2/cloud-sql-proxy.linux.amd64
fi
chmod 0755 /usr/local/bin/cloud-sql-proxy

install -m 0644 /dev/stdin /etc/systemd/system/warden-cloudsql-proxy.service <<UNIT
[Unit]
Description=Warden Cloud SQL Auth Proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=warden
RuntimeDirectory=warden-cloudsql
RuntimeDirectoryMode=0750
ExecStart=/usr/local/bin/cloud-sql-proxy --unix-socket=/run/warden-cloudsql ${INSTANCE_CONNECTION}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

install -m 0644 /dev/stdin /etc/systemd/system/warden-worker.service <<'UNIT'
[Unit]
Description=Warden cloud worker
Requires=warden-cloudsql-proxy.service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=warden
WorkingDirectory=/opt/warden
EnvironmentFile=/etc/warden-worker.env
Environment=PYTHONPATH=/opt/warden
Environment=PYTHONUNBUFFERED=1
Environment=MCHARNESS_DATA_ROOT=/var/lib/warden
Environment=WARDEN_BRAIN_BACKEND=postgres
Environment=MCHARNESS_PUBLIC_WRITE_ENABLED=false
Environment=MCHARNESS_TMUX_RUNNER_ENABLED=false
Environment=MCHARNESS_CODEX_RUNNER_ENABLED=false
Environment=WARDEN_QUEUE_BACKEND=pubsub
Environment=WARDEN_MISSIONS_TOPIC=projects/booming-key-500220-d9/topics/warden-missions
Environment=WARDEN_MISSIONS_SUBSCRIPTION=projects/booming-key-500220-d9/subscriptions/warden-worker-missions
Environment=WARDEN_QUEUE_CONSUMER_ENABLED=true
Environment=WARDEN_WORKER_EXECUTION_ENABLED=false
Environment=WARDEN_WORKER_ID=warden-worker
Environment=WARDEN_ARTIFACT_BACKEND=gcs
Environment=WARDEN_ARTIFACT_BUCKET=booming-key-500220-d9-warden-brain
Environment=WARDEN_WORKER_REPO_ROOT=/opt/warden
ExecStart=/opt/warden/.venv/bin/python -m uvicorn src.server.api:app --host 127.0.0.1 --port 8125 --log-level warning
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now warden-cloudsql-proxy.service
systemctl enable --now warden-worker.service
