"""Phase 6 Acceptance Test — Spark Drive Contradiction Regression & Reconciliation.

Verifies:
1. Old decision supports Drive architecture.
2. Drive adapter task is created and claimed (build-spark-drive-inbound-adapter-92d810).
3. Newer decision supersedes old architecture: "Spark integration uses native custom MCP, not Drive sync."
4. Captain reconciliation runs and automatically detects superseded_task.
5. Real task is cleanly superseded with decision provenance, retaining historical audit logs without deletion.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.warden.board import (
    find_task,
    revalidate_task_or_claim,
    supersede_task,
)
from src.warden.captain_orchestrator import (
    get_issue,
    list_issues,
    reconcile,
    resolve_issue,
)
from src.warden.workbench import STORE as WORKBENCH_STORE, WorkbenchMemoryRememberRequest


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


def test_spark_drive_contradiction_detection_and_reconciliation(tmp_path):
    board_root = Path(tmp_path / "warden_data" / "board")
    claimed_tasks_dir = board_root / "tasks" / "claimed"
    claims_dir = board_root / "claims"
    claimed_tasks_dir.mkdir(parents=True, exist_ok=True)
    claims_dir.mkdir(parents=True, exist_ok=True)

    task_id = "build-spark-drive-inbound-adapter-92d810"

    # 1. Create task build-spark-drive-inbound-adapter-92d810 in claimed status
    task_file = claimed_tasks_dir / f"{task_id}.json"
    task_file.write_text(json.dumps({
        "task_id": task_id,
        "title": "Build Spark Drive inbound adapter",
        "description": "Implement Google Drive sync inbound adapter for Spark integration.",
        "project": "warden",
        "priority": "urgent",
        "status": "claimed",
        "claimed_by": "codex",
        "based_on": ["dec_old_spark_drive"],
    }, indent=2))

    # 2. Record claim for codex on task
    claim_file = claims_dir / f"codex_{task_id}.json"
    claim_file.write_text(json.dumps({
        "ts": "2026-08-15T12:00:00Z",
        "agent": "codex",
        "action": "CLAIM",
        "task": task_id,
        "note": "Working on Drive sync for Spark",
    }, indent=2))

    # 3. Newer decision recorded in Warden memory:
    # "Spark integration uses native custom MCP, not Drive sync"
    decision = WORKBENCH_STORE.remember_memory(WorkbenchMemoryRememberRequest(
        scope="warden",
        content="Spark integration uses native custom MCP, not Drive sync. Drive adapter architecture is superseded.",
        source="operator",
        title="Spark Architecture: Native Custom MCP Over Drive Sync",
        tags=["spark", "mcp", "architecture", "decision"],
        kind="decision",
        agent_id="operator",
    ))

    # 4. Run Captain Reconciliation
    issues = reconcile(project="warden", trigger="decision.created")

    # 5. Assert Captain detected superseded_task
    matching_issues = [i for i in issues if i.kind == "superseded_task" and task_id in i.subjects]
    assert len(matching_issues) >= 1, "Captain failed to detect superseded Spark Drive task."

    issue = matching_issues[0]
    assert issue.severity == "high"
    assert "Spark uses native custom MCP" in issue.summary or "superseded" in issue.summary
    assert len(issue.evidence) >= 1

    # 6. Execute recommended resolution: supersede task
    superseded_task = supersede_task(
        task_id,
        reason=f"Superseded by decision '{decision.title}'",
        actor="captain_reconciler",
        superseded_by_decision=decision.memory_id,
    )
    assert superseded_task["status"] == "superseded"
    assert superseded_task["superseded_by_decision"] == decision.memory_id

    # 7. Resolve issue in ledger
    resolve_issue(issue.issue_id, resolution=f"Task {task_id} marked superseded", actor="captain")

    # 8. Prove task history is preserved and task revalidation reflects superseded status
    reval = revalidate_task_or_claim(task_id)
    assert reval["valid"] is False
    assert reval["status"] == "superseded"
    assert (board_root / "tasks" / "superseded" / f"{task_id}.json").exists()
    assert (claims_dir / f"codex_{task_id}.json").exists(), "Claim history must be preserved on disk."
