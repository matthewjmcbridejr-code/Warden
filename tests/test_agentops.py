"""Unit tests for Warden AgentOps and Evaluation Harness."""
from __future__ import annotations

from src.warden.agentops import AgentOpsReport, run_golden_eval_suite


def test_golden_eval_suite_execution():
    report = run_golden_eval_suite()
    assert isinstance(report, AgentOpsReport)
    assert report.suite == "warden-golden-v2"
    assert report.passed == 7
    assert report.failed == 0
    assert report.component_score == 1.0
    assert report.trajectory_score == 1.0
    assert report.outcome_score == 1.0
    assert len(report.results) == 7

    # Verify no hidden chain-of-thought tokens exist in results
    report_json = report.model_dump_json()
    assert "chain_of_thought" not in report_json
    assert "hidden_reasoning" not in report_json
