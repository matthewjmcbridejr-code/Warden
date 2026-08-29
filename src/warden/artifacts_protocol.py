"""Artifact-First Resource Protocol for Warden MCP 2.0.

Replaces giant inline tool response payloads with lightweight ArtifactRefs
delivered via Warden Resource URIs (warden://artifacts/<id>).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

ArtifactType = Literal[
    "plan", "diff", "report", "test_report", "proof",
    "screenshot", "log_excerpt", "document", "dataset",
    "context_pack", "agent_result",
]


class ArtifactRef(BaseModel):
    artifact_id: str
    uri: str
    type: ArtifactType = "agent_result"
    mime_type: str = "application/json"
    size: int
    sha256: str
    project: str = "warden"
    task_id: str | None = None
    run_id: str | None = None
    created_by: str = "warden"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    revision: int = 1
    storage_backend: str = "local_fs"
    immutable: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


_ARTIFACTS_STORE: dict[str, tuple[ArtifactRef, bytes]] = {}


def _gcs_enabled() -> bool:
    return os.getenv("WARDEN_ARTIFACT_BACKEND", "local").strip().lower() == "gcs" and bool(
        os.getenv("WARDEN_ARTIFACT_BUCKET", "").strip()
    )


def _gcs_blob(ref: ArtifactRef):
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("Install the cloud extra to use GCS artifacts") from exc
    client = storage.Client()
    bucket = client.bucket(os.environ["WARDEN_ARTIFACT_BUCKET"])
    return bucket.blob(f"artifacts/{ref.artifact_id}")


def store_artifact(
    content: bytes | str,
    *,
    type: ArtifactType = "agent_result",
    mime_type: str = "application/json",
    project: str = "warden",
    task_id: str | None = None,
    run_id: str | None = None,
    created_by: str = "warden",
    metadata: dict[str, Any] | None = None,
) -> ArtifactRef:
    """Stores content as an immutable ArtifactRef with SHA-256 integrity verification."""
    raw_bytes = content.encode("utf-8") if isinstance(content, str) else content
    sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
    artifact_id = f"art_{sha256_hash[:12]}"
    uri = f"warden://artifacts/{artifact_id}"

    ref = ArtifactRef(
        artifact_id=artifact_id,
        uri=uri,
        type=type,
        mime_type=mime_type,
        size=len(raw_bytes),
        sha256=sha256_hash,
        project=project,
        task_id=task_id,
        run_id=run_id,
        created_by=created_by,
        revision=1,
        immutable=True,
        metadata=metadata or {},
    )

    if _gcs_enabled():
        blob = _gcs_blob(ref)
        blob.metadata = {"warden_ref": json.dumps(ref.model_dump(mode="json"), sort_keys=True)}
        try:
            blob.upload_from_string(raw_bytes, content_type=mime_type, if_generation_match=0)
        except Exception as exc:
            # A deterministic artifact ID makes retries safe. A precondition
            # failure means the immutable object already exists.
            if getattr(exc, "code", None) != 412:
                raise
        ref.storage_backend = "gcs"
        ref.metadata = {**ref.metadata, "gcs_object": blob.name}
    _ARTIFACTS_STORE[artifact_id] = (ref, raw_bytes)
    return ref


def get_artifact_ref(artifact_id: str) -> ArtifactRef | None:
    """Retrieves metadata ref for an artifact."""
    item = _ARTIFACTS_STORE.get(artifact_id)
    if item:
        return item[0]
    if not _gcs_enabled():
        return None
    try:
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(os.environ["WARDEN_ARTIFACT_BUCKET"]).blob(f"artifacts/{artifact_id}")
        blob.reload()
        ref = ArtifactRef.model_validate(json.loads((blob.metadata or {})["warden_ref"]))
        _ARTIFACTS_STORE[artifact_id] = (ref, blob.download_as_bytes())
        return ref
    except (KeyError, ValueError, FileNotFoundError):
        return None


def read_artifact_content(artifact_id: str) -> tuple[ArtifactRef, bytes] | None:
    """Retrieves artifact ref and content bytes, verifying SHA-256 integrity."""
    item = _ARTIFACTS_STORE.get(artifact_id)
    if not item:
        ref = get_artifact_ref(artifact_id)
        item = _ARTIFACTS_STORE.get(artifact_id) if ref else None
    if not item:
        return None

    ref, content_bytes = item
    current_hash = hashlib.sha256(content_bytes).hexdigest()
    if current_hash != ref.sha256:
        raise ValueError(f"Artifact {artifact_id} failed SHA-256 integrity check!")

    return ref, content_bytes


def format_artifact_response(summary: str, artifacts: list[ArtifactRef]) -> dict[str, Any]:
    """Formats payload returning summary and lightweight ArtifactRefs instead of large inline blobs."""
    return {
        "summary": summary,
        "artifacts": [a.model_dump(mode="json") for a in artifacts],
    }
