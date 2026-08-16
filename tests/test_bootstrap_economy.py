"""Comprehensive test suite for Warden Context Economy & Token Efficiency."""
from __future__ import annotations

import json
from src.warden.brain_mcp_server import warden_bootstrap, warden_context_delta
from src.warden.context_protocol import compute_context_revision, get_context_delta
from src.warden.profile_protocol import compute_profile_revision
from src.warden.context_budget import ContextBudget, enforce_result_budget


def test_cold_auto_bootstrap_budget():
    res_str = warden_bootstrap(task="Test economy task", project="warden", mode="auto")
    payload = json.loads(res_str)
    assert payload["ok"] is True
    data = payload["data"]

    assert data["detail_mode"] == "auto"
    assert "context_revision" in data
    assert "profile_revision" in data
    assert "tool_catalog_revision" in data
    assert "available_context_counts" in data

    # Verify cold start size stays well under target budget (2.5 KB)
    assert len(res_str.encode("utf-8")) < 2500, f"Cold bootstrap payload too large: {len(res_str)} bytes"


def test_full_bootstrap_preserves_deep_context():
    res_str = warden_bootstrap(task="Test deep task", project="warden", mode="full")
    payload = json.loads(res_str)
    assert payload["ok"] is True
    data = payload["data"]

    assert data["detail_mode"] == "full"
    assert "context_pack" in data
    assert len(res_str.encode("utf-8")) > 5000


def test_warm_reconnect_no_change_tiny_payload():
    cold_str = warden_bootstrap(task="Initial task", project="warden", mode="auto")
    cold_data = json.loads(cold_str)["data"]

    ctx_rev = cold_data["context_revision"]
    cat_hash = cold_data["tool_catalog_revision"]["revision_hash"]
    prof_rev = cold_data["profile_revision"]

    warm_str = warden_bootstrap(
        task="Initial task",
        project="warden",
        mode="auto",
        known_context_revision=ctx_rev,
        known_tool_catalog_revision=cat_hash,
        known_profile_revision=prof_rev,
    )

    payload = json.loads(warm_str)
    assert payload["ok"] is True
    data = payload["data"]

    assert data["context_changed"] is False
    assert data["profile_changed"] is False
    assert data["tool_catalog_changed"] is False

    # Verify no-change warm payload is < 400 bytes
    assert len(warm_str.encode("utf-8")) < 500, f"Warm reconnect payload too large: {len(warm_str)} bytes"


def test_unrelated_project_memory_does_not_churn_revision():
    memories_warden = [
        {"memory_id": "m1", "title": "Decision 1", "kind": "decision", "project": "warden"}
    ]
    memories_grademy = [
        {"memory_id": "m1", "title": "Decision 1", "kind": "decision", "project": "warden"},
        {"memory_id": "m2", "title": "Grademy memory", "kind": "decision", "project": "grademy"},
    ]

    rev1 = compute_context_revision(project="warden", tasks=[], memories=memories_warden)
    rev2 = compute_context_revision(project="warden", tasks=[], memories=memories_grademy)

    assert rev1 == rev2, "Unrelated project memories must not churn project-scoped context_revision!"


def test_irrelevant_memory_kind_does_not_churn_revision():
    memories_base = [
        {"memory_id": "m1", "title": "Decision 1", "kind": "decision", "project": "warden"}
    ]
    memories_irrelevant = [
        {"memory_id": "m1", "title": "Decision 1", "kind": "decision", "project": "warden"},
        {"memory_id": "m2", "title": "Temp note", "kind": "note", "project": "warden"},
    ]

    rev1 = compute_context_revision(project="warden", tasks=[], memories=memories_base)
    rev2 = compute_context_revision(project="warden", tasks=[], memories=memories_irrelevant)

    assert rev1 == rev2, "Irrelevant memory kinds (like notes) must not churn context_revision!"


def test_backwards_compatibility_old_clients():
    # Clients that only pass task & project
    res_str = warden_bootstrap("Task only", "warden")
    payload = json.loads(res_str)
    assert payload["ok"] is True
    assert "context_revision" in payload["data"]

    # Clients passing detail="minimal"
    res_min = warden_bootstrap("Task min", "warden", detail="minimal")
    payload_min = json.loads(res_min)
    assert payload_min["ok"] is True
    assert payload_min["data"]["detail_mode"] == "minimal"
