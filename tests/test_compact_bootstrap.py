"""Phase 7 Acceptance Test — Compact vs Full Warden Bootstrap.

Verifies:
1. warden_bootstrap(detail="minimal") returns a compact header payload.
2. Minimal bootstrap payload size is materially smaller than full bootstrap.
3. warden_bootstrap(detail="full") remains available with full context pack.
"""
from __future__ import annotations

import json
import pytest

from src.warden.brain_mcp_server import warden_bootstrap


@pytest.fixture(autouse=True)
def isolated_roots(tmp_path, monkeypatch):
    data_dir = tmp_path / "warden_data"
    board_dir = data_dir / "board"
    board_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("WARDEN_DATA_ROOT", str(data_dir))
    monkeypatch.setenv("MCHARNESS_DATA_ROOT", str(data_dir))
    monkeypatch.setenv("WARDEN_BOARD_ROOT", str(board_dir))
    monkeypatch.setenv("MCTABLE_BOARD_ROOT", str(board_dir))
    return tmp_path


def test_minimal_vs_full_bootstrap_payload():
    task = "Verify Captain Orchestrator features"

    # Full bootstrap
    full_res_str = warden_bootstrap(task=task, project="warden", detail="full")
    full_res = json.loads(full_res_str)
    assert full_res["ok"] is True
    full_data = full_res["data"]
    assert full_data["detail_mode"] == "full"
    assert "context_pack" in full_data

    # Minimal bootstrap
    min_res_str = warden_bootstrap(task=task, project="warden", detail="minimal")
    min_res = json.loads(min_res_str)
    assert min_res["ok"] is True
    min_data = min_res["data"]
    assert min_data["detail_mode"] == "minimal"
    assert "operator_summary" in min_data
    assert "tool_catalog_revision" in min_data
    assert "context_pack" not in min_data

    # Size verification: minimal is materially smaller than full
    full_len = len(full_res_str)
    min_len = len(min_res_str)
    assert min_len < full_len, f"Minimal bootstrap size ({min_len}) must be smaller than full ({full_len})."
