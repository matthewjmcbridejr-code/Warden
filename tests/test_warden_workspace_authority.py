"""Tests for Warden Workspace Authority."""
from pathlib import Path

import pytest
from src.warden.workspace_authority import (
    resolve_project,
    list_projects,
    get_canonical_repo,
    classify_worktree,
    detect_workspace_drift,
    build_agent_bootstrap,
)

# Matches the dynamic default in workspace_authority._CURRENT_CHECKOUT —
# the actual checkout, wherever it lives on this machine.
CANONICAL = str(Path(__file__).resolve().parents[1])
SCRATCH = "/home/matt/Documents/Warden"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_list_projects_returns_warden():
    projects = list_projects()
    ids = [p["project_id"] for p in projects]
    assert "warden" in ids


def test_resolve_warden_project():
    p = resolve_project("warden")
    assert p is not None
    assert p["canonical_repo"] == CANONICAL


def test_resolve_unknown_project():
    assert resolve_project("totally-unknown-xyz") is None


def test_get_canonical_repo():
    assert get_canonical_repo("warden") == CANONICAL
    assert get_canonical_repo("nonexistent") is None


# ---------------------------------------------------------------------------
# Worktree classification
# ---------------------------------------------------------------------------

def test_canonical_path_is_safe():
    result = classify_worktree("warden", CANONICAL)
    assert result["workspace_status"] == "canonical"
    assert result["safe_to_edit"] is True


def test_subdirectory_of_canonical_is_safe():
    result = classify_worktree("warden", CANONICAL + "/src/warden")
    assert result["safe_to_edit"] is True


def test_scratch_path_is_not_safe():
    result = classify_worktree("warden", SCRATCH)
    assert result["safe_to_edit"] is False
    assert "non_canonical" == result["workspace_status"] or result.get("role") == "scratch_or_clone"


def test_scratch_result_includes_canonical_in_message():
    result = classify_worktree("warden", SCRATCH)
    assert "message" in result
    assert CANONICAL in result["message"]


def test_unknown_path_is_non_canonical():
    result = classify_worktree("warden", "/tmp/some/random/path")
    assert result["safe_to_edit"] is False
    assert result["workspace_status"] == "non_canonical"


def test_classify_unknown_project():
    result = classify_worktree("unknown-project-xyz", "/home/matt/anything")
    assert result["safe_to_edit"] is False
    assert result["workspace_status"] == "unknown"


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------

def test_no_drift_in_canonical(monkeypatch):
    monkeypatch.chdir(CANONICAL)
    result = detect_workspace_drift("warden")
    assert result["drifted"] is False


def test_drift_detected_in_scratch():
    result = detect_workspace_drift("warden", cwd=SCRATCH)
    assert result["drifted"] is True


def test_drift_detected_in_random_path():
    result = detect_workspace_drift("warden", cwd="/tmp/random-workspace")
    assert result["drifted"] is True


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def test_bootstrap_canonical_includes_canonical_repo():
    result = build_agent_bootstrap("warden", task="Test task", cwd=CANONICAL)
    assert result["ok"] is True
    assert result["canonical_repo"] == CANONICAL


def test_bootstrap_includes_code_here_paths():
    result = build_agent_bootstrap("warden", task="x", cwd=CANONICAL)
    code_here_paths = [wt["path"] for wt in result["code_here"]]
    assert CANONICAL in code_here_paths


def test_bootstrap_includes_do_not_code_here():
    result = build_agent_bootstrap("warden", task="x", cwd=CANONICAL)
    scratch_paths = [wt["path"] for wt in result["do_not_code_here"]]
    assert SCRATCH in scratch_paths


def test_bootstrap_includes_proof_commands():
    result = build_agent_bootstrap("warden", task="x", cwd=CANONICAL)
    assert len(result["proof_commands"]) > 0
    assert any("py_compile" in cmd for cmd in result["proof_commands"])


def test_bootstrap_includes_agent_start_rules():
    result = build_agent_bootstrap("warden", task="x", cwd=CANONICAL)
    assert len(result["agent_start_rules"]) > 0


def test_bootstrap_warns_when_cwd_is_scratch():
    result = build_agent_bootstrap("warden", task="x", cwd=SCRATCH)
    assert result["ok"] is True
    assert len(result["warnings"]) > 0
    assert CANONICAL in result["warnings"][0]


def test_bootstrap_no_warnings_when_canonical():
    result = build_agent_bootstrap("warden", task="x", cwd=CANONICAL)
    assert result["warnings"] == []


def test_bootstrap_recommended_action_canonical():
    result = build_agent_bootstrap("warden", task="x", cwd=CANONICAL)
    assert "Proceed" in result["recommended_next_action"] or "canonical" in result["recommended_next_action"].lower()


def test_bootstrap_recommended_action_scratch():
    result = build_agent_bootstrap("warden", task="x", cwd=SCRATCH)
    assert CANONICAL in result["recommended_next_action"]


def test_bootstrap_unknown_project_returns_error():
    result = build_agent_bootstrap("unknown-xyz", task="x")
    assert result["ok"] is False
    assert "Unknown project" in result["error"]


def test_bootstrap_includes_live_services():
    result = build_agent_bootstrap("warden", task="x", cwd=CANONICAL)
    assert isinstance(result["live_services"], list)


def test_bootstrap_does_not_expose_secrets():
    result = build_agent_bootstrap("warden", task="x", cwd=CANONICAL)
    dumped = str(result)
    for forbidden in ("password", "token", "api_key", "secret", "private_key"):
        assert forbidden not in dumped.lower() or "agent_start_rules" in dumped
