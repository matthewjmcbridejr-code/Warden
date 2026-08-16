"""Unit tests for Context Budget enforcement and artifact conversion."""
from __future__ import annotations

import json
from src.warden.context_budget import ContextBudget, enforce_result_budget


def test_enforce_result_budget_small_inline():
    small_payload = {"status": "ok", "message": "Quick check"}
    res = enforce_result_budget(
        summary="Small test result",
        payload=small_payload,
        project="warden",
    )

    assert res["inline"] is True
    assert res["summary"] == "Small test result"
    assert res["result"] == small_payload


def test_enforce_result_budget_oversized_artifact_conversion():
    # Generate ~12KB payload
    large_payload = {"logs": ["line " + str(i) for i in range(500)]}
    budget = ContextBudget(inline_tool_result_max_bytes=1000) # strict cap for test

    res = enforce_result_budget(
        summary="Oversized test result",
        payload=large_payload,
        project="warden",
        budget=budget,
    )

    assert "artifacts" in res
    assert len(res["artifacts"]) == 1
    art = res["artifacts"][0]
    assert art["uri"].startswith("warden://artifacts/art_")
    assert art["size"] > 1000
