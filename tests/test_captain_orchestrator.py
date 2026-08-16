"""Tests for Captain Orchestrator, Task Lifecycle, Reconciler, and Inference Providers.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.warden.board import (
    cancel_task,
    find_task,
    get_work_dependent_on_decision,
    revalidate_task_or_claim,
    supersede_task,
    update_task,
)
from src.warden.captain_orchestrator import (
    CaptainIssue,
    LocalCaptainInferenceProvider,
    VertexGeminiInferenceProvider,
    get_issue,
    list_issues,
    reconcile,
    resolve_issue,
    save_issue,
)


@pytest.fixture(autouse=True)
def isolated_warden_roots(tmp_path, monkeypatch):
    data_dir = tmp_path / "warden_data"
    board_dir = data_dir / "board"
    board_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("WARDEN_DATA_ROOT", str(data_dir))
    monkeypatch.setenv("MCHARNESS_DATA_ROOT", str(data_dir))
    monkeypatch.setenv("WARDEN_BOARD_ROOT", str(board_dir))
    monkeypatch.setenv("MCTABLE_BOARD_ROOT", str(board_dir))

    return tmp_path


def test_task_lifecycle_update_cancel_supersede(tmp_path):
    board_root = Path(tmp_path / "warden_data" / "board")
    draft_dir = board_root / "tasks" / "draft"
    draft_dir.mkdir(parents=True, exist_ok=True)

    task_id = "test-task-100"
    task_file = draft_dir / f"{task_id}.json"
    task_file.write_text(json.dumps({
        "task_id": task_id,
        "title": "Initial Task Title",
        "description": "Initial Task Description",
        "status": "draft",
        "based_on": ["dec_123"],
    }))

    # 1. Update task
    updated = update_task(task_id, {"title": "Updated Task Title", "priority": "high"}, actor="agent_test")
    assert updated["title"] == "Updated Task Title"
    assert updated["priority"] == "high"
    assert updated["updated_by"] == "agent_test"

    # 2. Revalidate active task
    reval = revalidate_task_or_claim(task_id)
    assert reval["valid"] is True
    assert reval["status"] == "draft"

    # 3. Supersede task
    superseded = supersede_task(
        task_id,
        reason="Superseded by native architecture",
        actor="captain",
        superseded_by_decision="dec_native_spark",
    )
    assert superseded["status"] == "superseded"
    assert superseded["supersede_reason"] == "Superseded by native architecture"
    assert (board_root / "tasks" / "superseded" / f"{task_id}.json").exists()
    assert not (board_root / "tasks" / "draft" / f"{task_id}.json").exists()

    # 4. Revalidate superseded task
    reval_sup = revalidate_task_or_claim(task_id)
    assert reval_sup["valid"] is False
    assert reval_sup["status"] == "superseded"


def test_task_cancel_lifecycle(tmp_path):
    board_root = Path(tmp_path / "warden_data" / "board")
    claimed_dir = board_root / "tasks" / "claimed"
    claimed_dir.mkdir(parents=True, exist_ok=True)

    task_id = "test-task-cancel-200"
    (claimed_dir / f"{task_id}.json").write_text(json.dumps({
        "task_id": task_id,
        "title": "Task to cancel",
        "status": "claimed",
        "claimed_by": "codex",
    }))

    cancelled = cancel_task(task_id, reason="No longer needed", actor="operator")
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_by"] == "operator"
    assert (board_root / "tasks" / "cancelled" / f"{task_id}.json").exists()

    reval = revalidate_task_or_claim(task_id)
    assert reval["valid"] is False
    assert reval["status"] == "cancelled"


def test_dependency_traversal(tmp_path):
    board_root = Path(tmp_path / "warden_data" / "board")
    assigned_dir = board_root / "tasks" / "assigned"
    claims_dir = board_root / "claims"
    assigned_dir.mkdir(parents=True, exist_ok=True)
    claims_dir.mkdir(parents=True, exist_ok=True)

    task_id = "task-dep-300"
    (assigned_dir / f"{task_id}.json").write_text(json.dumps({
        "task_id": task_id,
        "title": "Build feature dependent on decision 42",
        "status": "assigned",
        "based_on": ["dec_42"],
    }))

    (claims_dir / f"codex_{task_id}.json").write_text(json.dumps({
        "task": task_id,
        "agent": "codex",
        "action": "CLAIM",
    }))

    dep_res = get_work_dependent_on_decision("dec_42")
    assert dep_res["task_count"] == 1
    assert dep_res["claim_count"] == 1
    assert dep_res["dependent_tasks"][0]["task_id"] == task_id


def test_captain_issue_ledger_and_reconciliation(tmp_path):
    # Save issue
    issue = CaptainIssue(
        issue_id="iss_test_100",
        kind="stale_claim",
        severity="medium",
        summary="Stale claim detected for missing task",
        recommended_action="Clean claim",
    )
    saved = save_issue(issue)
    assert saved.issue_id == "iss_test_100"

    # Get issue
    fetched = get_issue("iss_test_100")
    assert fetched is not None
    assert fetched.kind == "stale_claim"

    # List issues
    all_issues = list_issues()
    assert len(all_issues) == 1

    # Resolve issue
    resolved = resolve_issue("iss_test_100", resolution="Cleaned up claim record", actor="captain")
    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.resolution == "captain: Cleaned up claim record"

    # Duplicate reconciliation run does not duplicate resolved issue
    reconcile_issues = reconcile(trigger="test_trigger")
    assert not any(i.issue_id == "iss_test_100" for i in reconcile_issues)


def test_captain_inference_providers():
    import asyncio

    async def _run():
        issue = CaptainIssue(
            issue_id="iss_inf_1",
            kind="superseded_task",
            severity="high",
            summary="Test superseded task issue",
            recommended_action="Supersede task",
        )
        context = {"project": "warden"}

        # Local provider
        local_provider = LocalCaptainInferenceProvider()
        local_assessment = await local_provider.assess(issue, context)
        assert local_assessment.classification == "superseded_task"
        assert local_assessment.confidence > 0.5

        # Vertex Gemini provider (mock test / ADC fallback check)
        vertex_provider = VertexGeminiInferenceProvider(project_id="booming-key-500220-d9", location="global", model="gemini-2.5-flash")
        vertex_assessment = await vertex_provider.assess(issue, context)
        assert isinstance(vertex_assessment.classification, str)

        # Loud failure when fallback_enabled=False on invalid model
        invalid_provider = VertexGeminiInferenceProvider(project_id="invalid-proj", location="us-central1", model="invalid-model-name-xyz")
        try:
            await invalid_provider.assess(issue, context, fallback_enabled=False)
            assert False, "Should have raised RuntimeError when fallback_enabled=False"
        except RuntimeError as exc:
            assert "fallback_enabled=False" in str(exc)

    asyncio.run(_run())


def test_detect_duplicate_active_work(tmp_path):
    board_root = Path(tmp_path / "warden_data" / "board")
    draft_dir = board_root / "tasks" / "draft"
    draft_dir.mkdir(parents=True, exist_ok=True)

    (draft_dir / "task-1.json").write_text(json.dumps({"task_id": "task-1", "title": "Build Feature Alpha", "status": "draft"}))
    (draft_dir / "task-2.json").write_text(json.dumps({"task_id": "task-2", "title": "Build Feature Alpha", "status": "draft"}))

    from src.warden.captain_orchestrator import detect_duplicate_active_work
    issues = detect_duplicate_active_work()
    assert len(issues) >= 1
    assert issues[0].kind == "duplicate_work"


def test_detect_orphaned_handoffs(tmp_path):
    board_root = Path(tmp_path / "warden_data" / "board")
    review_dir = board_root / "tasks" / "needs_review"
    handoffs_dir = board_root / "handoffs"
    review_dir.mkdir(parents=True, exist_ok=True)
    handoffs_dir.mkdir(parents=True, exist_ok=True)

    task_id = "task-orphaned-1"
    (review_dir / f"{task_id}.json").write_text(json.dumps({"task_id": task_id, "title": "Orphaned Task", "status": "needs_review", "claimed_by": "codex"}))
    (handoffs_dir / f"handoff_{task_id}.json").write_text(json.dumps({"task": task_id, "from_agent": "codex", "to_agent": "gemini"}))

    from src.warden.captain_orchestrator import detect_orphaned_handoffs
    issues = detect_orphaned_handoffs()
    assert len(issues) >= 1
    assert issues[0].kind == "orphaned_handoff"


def test_detect_failed_or_stale_proofs(tmp_path):
    board_root = Path(tmp_path / "warden_data" / "board")
    failed_dir = board_root / "tasks" / "failed"
    failed_dir.mkdir(parents=True, exist_ok=True)

    (failed_dir / "task-failed-1.json").write_text(json.dumps({"task_id": "task-failed-1", "title": "Failing Task", "status": "failed"}))

    from src.warden.captain_orchestrator import detect_failed_or_stale_proofs
    issues = detect_failed_or_stale_proofs()
    assert len(issues) >= 1
    assert issues[0].kind == "proof_failed"


def test_complete_and_fail_task_lifecycle(tmp_path):
    board_root = Path(tmp_path / "warden_data" / "board")
    draft_dir = board_root / "tasks" / "draft"
    draft_dir.mkdir(parents=True, exist_ok=True)

    t1 = "task-complete-1"
    t2 = "task-fail-1"
    (draft_dir / f"{t1}.json").write_text(json.dumps({"task_id": t1, "title": "Complete me", "status": "draft"}))
    (draft_dir / f"{t2}.json").write_text(json.dumps({"task_id": t2, "title": "Fail me", "status": "draft"}))

    from src.warden.board import complete_task, fail_task, revalidate_task_or_claim
    c_res = complete_task(t1, actor="agent_a", note="All done")
    assert c_res["status"] == "completed"

    f_res = fail_task(t2, reason="Gate check failed", actor="agent_b")
    assert f_res["status"] == "failed"

    reval_c = revalidate_task_or_claim(t1)
    assert reval_c["valid"] is False
    assert reval_c["status"] == "completed"

    reval_f = revalidate_task_or_claim(t2)
    assert reval_f["valid"] is True or reval_f["status"] == "failed"


def test_on_state_event_coverage(tmp_path):
    from src.warden.captain_orchestrator import on_state_event
    event_types = [
        "task.created",
        "task.claimed",
        "task.cancelled",
        "task.superseded",
        "task.completed",
        "task.failed",
        "handoff.created",
        "decision.created",
        "proof.submitted",
        "proof.rejected",
        "service.health_changed",
        "tool_catalog.changed",
    ]
    for evt in event_types:
        issues = on_state_event(evt, project="warden")
        assert isinstance(issues, list)


def test_check_client_tool_catalog_freshness():
    from src.warden.captain_orchestrator import check_client_tool_catalog_freshness, _get_served_native_count
    served_cnt = _get_served_native_count()
    fresh_res = check_client_tool_catalog_freshness("client_a", known_count=served_cnt)
    assert fresh_res["is_stale"] is False

    stale_res = check_client_tool_catalog_freshness("client_b", known_count=served_cnt + 10)
    assert stale_res["is_stale"] is True
    assert "reconnect" in stale_res["recommended_action"].lower() or "refresh" in stale_res["recommended_action"].lower()


def test_captain_desk_endpoint_aggregation():
    from src.warden.api import api_captain_desk
    data = api_captain_desk(project="warden")
    assert data["ok"] is True
    assert "captain" in data
    assert "noticed" in data
    assert "fixed" in data
    assert "needs_you" in data
    assert "agents" in data
    assert "board" in data
    assert "services" in data
    assert "activity" in data

    svc = data["services"]
    assert svc["native_tool_count"] >= 60
    assert svc["upstream_tool_count"] == 43
    assert svc["total_tool_count"] >= 103


