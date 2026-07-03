#!/bin/bash
# scripts/marius_brain_gcs_setup.sh
# Marius Google Cloud Storage setup for searchable memory

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GCLOUD_PATH="${REPO_ROOT}/google-cloud-sdk/path.bash.inc"

if [ -f "${GCLOUD_PATH}" ]; then
    source "${GCLOUD_PATH}"
fi

PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "${PROJECT_ID}" ]; then
    echo "ERROR: No active Google Cloud project. Run 'gcloud config set project <PROJECT_ID>'"
    exit 1
fi

# Rules:
# - dry-run must not create bucket
# - dry-run must not upload
# - upload requires explicit --upload
# - bucket creation requires explicit --create-bucket
# - default bucket must be marius-brain-292003335586

BUCKET_NAME="marius-brain-292003335586"
LOCATION="us-central1"

# Handle arguments
CREATE_BUCKET=false
UPLOAD=false

for arg in "$@"; do
    case $arg in
        --create-bucket)
            CREATE_BUCKET=true
            shift
            ;;
        --upload)
            UPLOAD=true
            shift
            ;;
        --bucket=*)
            BUCKET_NAME="${arg#*=}"
            shift
            ;;
    esac
done

echo "== Marius Brain GCS Setup =="
echo "Project: ${PROJECT_ID}"
echo "Bucket:  gs://${BUCKET_NAME}"
echo "Region:  ${LOCATION}"

if [ "$CREATE_BUCKET" = true ]; then
    if gcloud storage buckets describe "gs://${BUCKET_NAME}" >/dev/null 2>&1; then
        echo "Bucket already exists."
    else
        echo "Creating bucket..."
        gcloud storage buckets create "gs://${BUCKET_NAME}" --project="${PROJECT_ID}" --location="${LOCATION}" --uniform-bucket-level-access
        echo "Bucket created."
    fi
else
    echo "Skipping bucket creation (use --create-bucket to force)."
fi

if [ "$UPLOAD" = true ]; then
    echo "Rebuilding safe brain exports..."
    "${REPO_ROOT}/.venv/bin/python" "${REPO_ROOT}/scripts/rebuild_brain_exports.py"

    EXPORTS_DIR="${HOME}/.local/share/marius/brain/exports"
    if [ -d "${EXPORTS_DIR}" ]; then
        echo "Uploading exports to gs://${BUCKET_NAME}/brain/exports/ ..."
        gcloud storage cp "${EXPORTS_DIR}"/*.jsonl "gs://${BUCKET_NAME}/brain/exports/" --project="${PROJECT_ID}"
        echo "Upload complete."
    else
        echo "ERROR: No local exports found."
        exit 1
    fi
else
    echo "Dry run: use --upload to sync local brain to GCS."
fi

echo "Done."
