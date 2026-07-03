#!/bin/bash
# scripts/google_agent_search_doctor.sh
# Marius Google Agent Search / marius-brain Foundation Doctor

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GCLOUD_PATH="${REPO_ROOT}/google-cloud-sdk/path.bash.inc"

if [ -f "${GCLOUD_PATH}" ]; then
    source "${GCLOUD_PATH}"
fi

echo "== gcloud Binary =="
which gcloud || echo "gcloud NOT FOUND"

echo "== gcloud Version =="
gcloud --version || true

echo "== Active Account =="
gcloud auth list --filter=status:ACTIVE --format="value(account)"

echo "== Active Project =="
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
echo "${PROJECT_ID:-UNSET}"

if [ -n "${PROJECT_ID}" ]; then
    echo "== Billing Status =="
    gcloud billing projects describe "${PROJECT_ID}" --format="table(projectId,billingAccountName,billingEnabled)" 2>/dev/null || echo "Billing visibility issue"
    
    echo "== API Status =="
    gcloud services list --enabled --project "${PROJECT_ID}" \
        --filter="NAME:(discoveryengine.googleapis.com OR storage.googleapis.com OR aiplatform.googleapis.com)" \
        --format="table(config.name,state)"
fi

echo "== ADC Check =="
if gcloud auth application-default print-access-token >/dev/null 2>&1; then
    echo "ADC: OK"
else
    echo "ADC: MISSING"
    echo "Run: gcloud auth application-default login --no-launch-browser"
fi

echo "== Dependency Check =="
if [ -d "${REPO_ROOT}/.venv" ]; then
    if "${REPO_ROOT}/.venv/bin/python" -c "import google.cloud.discoveryengine" 2>/dev/null; then
        echo "google-cloud-discoveryengine: INSTALLED"
    else
        echo "google-cloud-discoveryengine: MISSING"
        echo "Run: ${REPO_ROOT}/.venv/bin/python -m pip install google-cloud-discoveryengine"
    fi
fi
