#!/usr/bin/env bash
set -euo pipefail

# Dedicated always-on MCP edge. Brain memory and MCP identity documents are in
# Cloud SQL; McTable runs privately on the same VM and is mounted read-only by
# Warden. Set the instance attribute MCP_EDGE_DOMAIN to the final DNS name
# before the OAuth issuer is cut over.
PROJECT_ID="booming-key-500220-d9"
INSTANCE_CONNECTION="${PROJECT_ID}:us-central1:warden-brain"
REPO_URL="https://github.com/matthewjmcbridejr-code/Warden.git"
REPO_BRANCH="feat/mission-control-product-completion"
APP_DIR="/opt/warden"
DATA_DIR="/var/lib/warden-mcp-edge"
MCTABLE_DIR="/opt/mctable"
MCTABLE_DATA_DIR="/var/lib/mctable-edge"
MCTABLE_REPO_URL="https://github.com/matthewjmcbridejr-code/marius-mind-code.git"
MCTABLE_REPO_BRANCH="main"
DOMAIN="$(curl -fsS -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/attributes/MCP_EDGE_DOMAIN' \
  2>/dev/null || true)"
DOMAIN="${DOMAIN:-mcp.mctable.online}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git gnupg python3-venv

# Keep semantic memory search available on the small edge VM without a
# heavyweight model.  Ollama stores the model behind its local API; Warden
# only needs the service and model name, never provider credentials.
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
systemctl enable --now ollama
ollama pull nomic-embed-text

# Caddy provides HTTPS termination and automatic renewal once DOMAIN's A/AAAA
# records point at this VM. The old McServer DNS record is not changed here.
install -d -m 0755 /etc/apt/keyrings
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  -o /etc/apt/sources.list.d/caddy-stable.list
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

id -u warden >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/warden --shell /usr/sbin/nologin warden
id -u mctable >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/mctable --shell /usr/sbin/nologin mctable
mkdir -p "${APP_DIR}" "${DATA_DIR}" "${MCTABLE_DIR}" "${MCTABLE_DATA_DIR}"
chown -R warden:warden "${APP_DIR}" "${DATA_DIR}"
chown -R mctable:mctable "${MCTABLE_DIR}" "${MCTABLE_DATA_DIR}"

git_warden() {
  runuser -u warden -- git "$@"
}

if [ ! -d "${APP_DIR}/.git" ]; then
  git_warden clone --branch "${REPO_BRANCH}" --single-branch "${REPO_URL}" "${APP_DIR}"
else
  git_warden -C "${APP_DIR}" fetch origin "${REPO_BRANCH}"
  git_warden -C "${APP_DIR}" merge --ff-only "origin/${REPO_BRANCH}"
fi

git_mctable() {
  runuser -u mctable -- git "$@"
}

if [ ! -d "${MCTABLE_DIR}/.git" ]; then
  git_mctable clone --branch "${MCTABLE_REPO_BRANCH}" --single-branch "${MCTABLE_REPO_URL}" "${MCTABLE_DIR}"
else
  git_mctable -C "${MCTABLE_DIR}" fetch origin "${MCTABLE_REPO_BRANCH}"
  git_mctable -C "${MCTABLE_DIR}" merge --ff-only "origin/${MCTABLE_REPO_BRANCH}"
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
    | python3 -c 'import base64,json,sys; sys.stdout.write(base64.b64decode(json.load(sys.stdin)["payload"]["data"]).decode())'
}

# Transform Cloud Run's Cloud SQL socket path to the local Auth Proxy socket.
# Neither the database password nor the DSN is logged.
RAW_DSN="$(secret_value WARDEN_BRAIN_DATABASE_URL)"
BRAIN_DSN="$(RAW_DSN="${RAW_DSN}" python3 -c 'import os; d=os.environ["RAW_DSN"]; print(d.replace("/cloudsql/booming-key-500220-d9:us-central1:warden-brain", "/run/warden-cloudsql/booming-key-500220-d9:us-central1:warden-brain"))')"
OAUTH_PASSPHRASE="$(secret_value MCP_OAUTH_OWNER_PASSPHRASE)"
SLACK_BOT_TOKEN="$(secret_value WARDEN_SLACK_BOT_TOKEN)"
SLACK_SIGNING_SECRET="$(secret_value WARDEN_SLACK_SIGNING_SECRET)"
MCTABLE_API_KEY="$(secret_value MCTABLE_API_KEY 2>/dev/null || true)"
umask 077
printf '%s\n' \
  "WARDEN_BRAIN_DATABASE_URL=${BRAIN_DSN}" \
  "MCP_OAUTH_OWNER_PASSPHRASE=${OAUTH_PASSPHRASE}" \
  "WARDEN_MCP_HUB_URL=http://127.0.0.1:8082/mcp/" \
  "WARDEN_MCP_HUB_TOKEN=${MCTABLE_API_KEY}" \
  "SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}" \
  "SLACK_SIGNING_SECRET=${SLACK_SIGNING_SECRET}" \
  > /etc/warden-mcp-edge.env
chown root:warden /etc/warden-mcp-edge.env
chmod 0640 /etc/warden-mcp-edge.env
unset RAW_DSN BRAIN_DSN OAUTH_PASSPHRASE SLACK_BOT_TOKEN SLACK_SIGNING_SECRET

if [ -n "${MCTABLE_API_KEY}" ]; then
  printf 'MCTABLE_API_KEY=%s\n' "${MCTABLE_API_KEY}" > /etc/mctable-edge.env
else
  : > /etc/mctable-edge.env
fi
chown root:mctable /etc/mctable-edge.env
chmod 0640 /etc/mctable-edge.env
unset MCTABLE_API_KEY

python3 -m venv "${MCTABLE_DIR}/.venv"
"${MCTABLE_DIR}/.venv/bin/pip" install --upgrade pip
"${MCTABLE_DIR}/.venv/bin/pip" install "${MCTABLE_DIR}[cloud]" 2>/dev/null || \
  "${MCTABLE_DIR}/.venv/bin/pip" install -r "${MCTABLE_DIR}/requirements.txt"
chown -R mctable:mctable "${MCTABLE_DIR}" "${MCTABLE_DATA_DIR}"

# Pin the proxy version used by the startup contract and run it with the VM's
# attached service account (roles/cloudsql.client; no static key file).
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

install -m 0644 /dev/stdin /etc/systemd/system/warden-mcp-edge.service <<'UNIT'
[Unit]
Description=Warden Cloud Brain MCP edge
Requires=warden-cloudsql-proxy.service mctable-edge.service
After=warden-cloudsql-proxy.service mctable-edge.service network-online.target
Wants=network-online.target

[Service]
Type=simple
User=warden
WorkingDirectory=/opt/warden
EnvironmentFile=/etc/warden-mcp-edge.env
Environment=PYTHONPATH=/opt/warden/src
Environment=PYTHONUNBUFFERED=1
Environment=MCHARNESS_DATA_ROOT=/var/lib/warden-mcp-edge
Environment=WARDEN_BRAIN_BACKEND=postgres
Environment=WARDEN_EMBED_MODEL=nomic-embed-text
Environment=WARDEN_EMBED_TIMEOUT_SECONDS=60
Environment=WARDEN_MCP_STATE_BACKEND=postgres
Environment=WARDEN_MCP_HUB_ENABLED=true
Environment=WARDEN_MCP_HUB_URL=http://127.0.0.1:8082/mcp/
Environment=WARDEN_MCP_HUB_POLICY=read_only
Environment=MCP_OAUTH_ISSUER_URL=https://mcp.mctable.online
Environment=WARDEN_URL=https://warden-api-cpjzhcvbha-uc.a.run.app
Environment=WARDEN_AUTH_MODE=gce_metadata
Environment=WARDEN_AUTH_AUDIENCE=https://warden-api-cpjzhcvbha-uc.a.run.app
ExecStartPre=/bin/sh -c 'for attempt in $(seq 1 30); do curl -fsS http://127.0.0.1:8082/health >/dev/null && exit 0; sleep 2; done; exit 1'
ExecStart=/opt/warden/.venv/bin/python -m warden.brain_mcp_server --http --host 127.0.0.1 --port 8126
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

install -m 0644 "${APP_DIR}/scripts/systemd/mctable-edge.service" /etc/systemd/system/mctable-edge.service
install -m 0644 "${APP_DIR}/scripts/systemd/warden-mcp-edge.service" /etc/systemd/system/warden-mcp-edge.service

install -m 0644 /dev/stdin /etc/caddy/Caddyfile <<UNIT
${DOMAIN} {
    encode gzip
    reverse_proxy 127.0.0.1:8126
}
UNIT

systemctl daemon-reload
systemctl enable --now warden-cloudsql-proxy.service
systemctl enable --now warden-mcp-edge.service
systemctl enable caddy.service
systemctl restart caddy.service
