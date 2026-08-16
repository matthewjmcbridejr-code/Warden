"""Unit tests for Artifact-First Resource Protocol."""
from __future__ import annotations

import json
import pytest
from src.warden.artifacts_protocol import (
    ArtifactRef,
    format_artifact_response,
    get_artifact_ref,
    read_artifact_content,
    store_artifact,
)


def test_store_and_read_artifact():
    content = json.dumps({"test_report": "905 passed", "suite": "warden-core"})
    ref = store_artifact(
        content=content,
        type="test_report",
        mime_type="application/json",
        project="warden",
        created_by="codex",
    )

    assert isinstance(ref, ArtifactRef)
    assert ref.artifact_id.startswith("art_")
    assert ref.uri == f"warden://artifacts/{ref.artifact_id}"
    assert ref.type == "test_report"
    assert ref.immutable is True
    assert ref.size == len(content.encode("utf-8"))

    fetched = get_artifact_ref(ref.artifact_id)
    assert fetched is not None
    assert fetched.sha256 == ref.sha256

    result = read_artifact_content(ref.artifact_id)
    assert result is not None
    read_ref, read_bytes = result
    assert read_bytes.decode("utf-8") == content
    assert read_ref.sha256 == ref.sha256


def test_format_artifact_response():
    ref1 = store_artifact("diff --git a/src b/src", type="diff", mime_type="text/x-diff")
    resp = format_artifact_response(summary="Feature diff generated", artifacts=[ref1])

    assert resp["summary"] == "Feature diff generated"
    assert len(resp["artifacts"]) == 1
    assert resp["artifacts"][0]["uri"] == ref1.uri
    assert resp["artifacts"][0]["sha256"] == ref1.sha256
