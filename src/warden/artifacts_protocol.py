"""Artifact-First Resource Protocol for Warden MCP 2.0.

Replaces giant inline tool response payloads with lightweight ArtifactRefs
delivered via Warden Resource URIs (warden://artifacts/<id>).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

MCTABLE_ROOT = Path(os.getenv("MCHARNESS_DATA_ROOT", "_mctable"))

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


def _local_artifact_root() -> Path:
    root = Path(os.getenv("WARDEN_ARTIFACT_ROOT", str(MCTABLE_ROOT / "artifacts"))).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _valid_artifact_id(artifact_id: str) -> bool:
    return bool(re.fullmatch(r"art_[a-f0-9]{12}", artifact_id))


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
        ref.storage_backend = "gcs"
        ref.metadata = {**ref.metadata, "gcs_object": blob.name}
        blob.metadata = {"warden_ref": json.dumps(ref.model_dump(mode="json"), sort_keys=True)}
        try:
            blob.upload_from_string(raw_bytes, content_type=mime_type, if_generation_match=0)
        except Exception as exc:
            # A deterministic artifact ID makes retries safe. A precondition
            # failure means the immutable object already exists.
            if getattr(exc, "code", None) != 412:
                raise
    else:
        # Local mode must remain usable across MCP requests and process
        # restarts. Content is immutable and addressed by its SHA-256 prefix,
        # so a pre-existing file is safe to reuse.
        root = _local_artifact_root()
        content_path = root / f"{artifact_id}.bin"
        metadata_path = root / f"{artifact_id}.json"
        if not content_path.exists():
            content_path.write_bytes(raw_bytes)
        if not metadata_path.exists():
            metadata_path.write_text(json.dumps(ref.model_dump(mode="json"), sort_keys=True))
    _ARTIFACTS_STORE[artifact_id] = (ref, raw_bytes)
    return ref


def get_artifact_ref(artifact_id: str) -> ArtifactRef | None:
    """Retrieves metadata ref for an artifact."""
    item = _ARTIFACTS_STORE.get(artifact_id)
    if item:
        return item[0]
    if not _valid_artifact_id(artifact_id):
        return None
    if not _gcs_enabled():
        try:
            root = _local_artifact_root()
            metadata_path = root / f"{artifact_id}.json"
            content_path = root / f"{artifact_id}.bin"
            if not metadata_path.exists() or not content_path.exists():
                return None
            ref = ArtifactRef.model_validate(json.loads(metadata_path.read_text()))
            _ARTIFACTS_STORE[artifact_id] = (ref, content_path.read_bytes())
            return ref
        except (OSError, ValueError, json.JSONDecodeError):
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


def list_artifact_refs(project: str = "", limit: int = 100) -> list[ArtifactRef]:
    """List metadata from memory plus durable local/GCS-backed references."""
    refs: dict[str, ArtifactRef] = {artifact_id: ref for artifact_id, (ref, _) in _ARTIFACTS_STORE.items()}
    if _gcs_enabled():
        try:
            from google.cloud import storage
            client = storage.Client()
            for blob in client.bucket(os.environ["WARDEN_ARTIFACT_BUCKET"]).list_blobs(prefix="artifacts/"):
                try:
                    metadata = blob.metadata or {}
                    ref = ArtifactRef.model_validate(json.loads(metadata["warden_ref"]))
                except (KeyError, ValueError, json.JSONDecodeError):
                    continue
                refs[ref.artifact_id] = ref
        except Exception:
            # Listing is best-effort; direct get by URI remains authoritative.
            pass
    else:
        try:
            for metadata_path in _local_artifact_root().glob("art_*.json"):
                try:
                    ref = ArtifactRef.model_validate(json.loads(metadata_path.read_text()))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                refs[ref.artifact_id] = ref
        except OSError:
            pass
    rows = [ref for ref in refs.values() if not project or ref.project == project]
    rows.sort(key=lambda ref: ref.created_at, reverse=True)
    return rows[: max(1, min(int(limit), 100))]


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
