#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/matthewjmcbridejr-code/Warden.git"
REPO_BRANCH="feat/mission-control-product-completion"
APP_DIR="/opt/warden"
DATA_DIR="/var/lib/warden"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3-venv python3-pip build-essential tmux

id -u warden >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/warden --shell /usr/sbin/nologin warden
mkdir -p "${APP_DIR}" "${DATA_DIR}"
chown -R warden:warden "${APP_DIR}" "${DATA_DIR}"

if [ ! -d "${APP_DIR}/.git" ]; then
  git clone --branch "${REPO_BRANCH}" --single-branch "${REPO_URL}" "${APP_DIR}"
else
  git -C "${APP_DIR}" fetch origin "${REPO_BRANCH}"
  git -C "${APP_DIR}" merge --ff-only "origin/${REPO_BRANCH}"
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install "${APP_DIR}[cloud]"
chown -R warden:warden "${APP_DIR}" "${DATA_DIR}"

install -m 0644 /dev/stdin /etc/systemd/system/warden-worker.service <<'UNIT'
[Unit]
Description=Warden cloud worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=warden
WorkingDirectory=/opt/warden
Environment=PYTHONPATH=/opt/warden
Environment=PYTHONUNBUFFERED=1
Environment=MCHARNESS_DATA_ROOT=/var/lib/warden
Environment=MCHARNESS_PUBLIC_WRITE_ENABLED=false
Environment=MCHARNESS_TMUX_RUNNER_ENABLED=false
Environment=MCHARNESS_CODEX_RUNNER_ENABLED=false
Environment=WARDEN_QUEUE_BACKEND=pubsub
Environment=WARDEN_MISSIONS_TOPIC=projects/booming-key-500220-d9/topics/warden-missions
Environment=WARDEN_MISSIONS_SUBSCRIPTION=projects/booming-key-500220-d9/subscriptions/warden-worker-missions
Environment=WARDEN_QUEUE_CONSUMER_ENABLED=true
Environment=WARDEN_WORKER_EXECUTION_ENABLED=false
Environment=WARDEN_WORKER_ID=warden-worker
ExecStart=/opt/warden/.venv/bin/python -m uvicorn src.server.api:app --host 127.0.0.1 --port 8125 --log-level warning
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now warden-worker.service
