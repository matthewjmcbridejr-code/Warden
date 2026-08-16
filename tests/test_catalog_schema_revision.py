"""Unit tests for Tool Catalog Schema Revision hashing and freshness."""
from __future__ import annotations

import json
from src.warden.brain_mcp_server import compute_tool_catalog_revision, mcp, warden_remember


def test_tool_catalog_schema_revision_stability():
    rev1 = compute_tool_catalog_revision()
    assert rev1["revision_hash"].startswith("cat_rev_")

    # Re-computing on same state produces exact same revision hash
    rev2 = compute_tool_catalog_revision()
    assert rev1["revision_hash"] == rev2["revision_hash"]

    # Writing memory does NOT churn tool catalog revision
    warden_remember(kind="note", text="Unrelated memory write test", project="warden")
    rev3 = compute_tool_catalog_revision()
    assert rev1["revision_hash"] == rev3["revision_hash"], "Memory write must not alter tool catalog revision!"


def test_tool_catalog_schema_revision_changes_on_parameter_or_annotation_change():
    rev1 = compute_tool_catalog_revision()

    # Simulate tool parameter modification
    target_tool = mcp._tool_manager._tools.get("warden_bootstrap")
    assert target_tool is not None

    orig_parameters = dict(getattr(target_tool, "parameters", {}))
    try:
        # Modify parameters
        target_tool.parameters = dict(orig_parameters, extra_field={"type": "string"})
        rev_param_changed = compute_tool_catalog_revision()
        assert rev1["revision_hash"] != rev_param_changed["revision_hash"], "Parameter modification MUST alter catalog revision!"

        # Modify annotations
        target_tool.parameters = orig_parameters
        target_tool.annotations = {"read_only": False, "risk_class": "critical"}
        rev_annot_changed = compute_tool_catalog_revision()
        assert rev1["revision_hash"] != rev_annot_changed["revision_hash"], "Annotation modification MUST alter catalog revision!"

    finally:
        target_tool.parameters = orig_parameters
        target_tool.annotations = None
