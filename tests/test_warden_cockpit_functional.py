from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from src.warden.api import ARTIFACT_BODY_ROOT
from src.warden.captain import CAPTAIN_ROOT
from src.warden.workbench import WORKBENCH_ROOT
from src.server.api import app


def _reset_runtime_state() -> None:
    for directory in [WORKBENCH_ROOT, CAPTAIN_ROOT, ARTIFACT_BODY_ROOT]:
        if directory.exists():
            shutil.rmtree(directory)


def test_functional_cockpit_page_is_served_with_control_plane_labels():
    client = TestClient(app)
    response = client.get("/web/warden/index.html")
    assert response.status_code == 200
    for snippet in [
        "Warden",
        "by Marius Systems",
        "Control Room",
        "Powered by McHarness",
        "nav-mission",
        "Control Room",
        "mission-command",
        "Supervise missions, runs, and proof gates.",
        "cr-command-center",
        "cr-tab-timeline",
        "rail-proof-gates",
        "rail-runner-sessions",
        "command-palette",
        "demo-mode-banner",
        "run-detail-decisions",
        "run-detail-next-actions",
        "Decision History",
        "Next Allowed Manual Action",
        "operator-inspector",
        "inspector-next-move",
        "warden-topbar",
        "warden-sidebar",
        "nav-tasks",
        "No active task plan yet",
        "settings-captain-status",
        "settings-safety-list",
        "settings-codex-status",
        "settings-jules-status",
        "Public runner — Off",
        "Private runner — Off",
        "Shell access — Restricted",
        "Agent registration — Private",
        "Captain orchestrates",
        "Agents",
        "agent-group-captain",
        "CLI Agents",
        "Remote Agents",
        "captain-profile-panel",
        "Create Plan",
        "captain-create-plan-btn",
        "codex-open-monitor",
        "codex-configure",
        "Executes approved CLI tasks",
        "Codex CLI",
        "Add Agent",
        "New agents require an adapter",
        "add-agent-modal",
        "add-agent-step-choose",
        "Test Connection",
        "captain-deck-modal",
        "runs-list",
        "evidence-list",
        "run-detail-modal",
        "evidence-detail-modal",
        "current-mission-plan",
        "captain-plan-steps",
        "captain-plan-controls",
        "Deploy Current Step",
    ]:
        assert snippet in response.text
    for removed_snippet in [
        "SERVER CONTROL PLANE",
        "Advanced / Legacy Cockpit",
    ]:
        assert removed_snippet not in response.text


def test_mcharness_control_plane_loop_persists_after_reload():
    _reset_runtime_state()
    try:
        with TestClient(app) as client:
            repos = client.get("/api/mcharness/repos")
            assert repos.status_code == 200
            assert any(item["path"] == str(Path(__file__).resolve().parents[1]) for item in repos.json()["repos"])

            lanes = client.get("/api/mcharness/agent-lanes")
            assert lanes.status_code == 200
            assert any(item["lane_id"] == "manual_paste" and item["implemented"] for item in lanes.json()["lanes"])

            created = client.post(
                "/api/mcharness/sessions",
                json={
                    "title": "Functional cockpit session",
                    "objective": "Prove the repo/lane/session/manual-result gate loop through Warden APIs.",
                    "plan_instruction": "Create a bounded queue, collect manual result artifacts, and block continuation until the gate is approved.",
                    "repo_path": str(Path(__file__).resolve().parents[1]),
                    "agent_lane": "manual_paste",
                },
            )
            assert created.status_code == 200, created.text
            created_payload = created.json()
            session_id = created_payload["session_id"]
            run_id = created_payload["run"]["run_id"]
            assert created_payload["thread"]["metadata"]["repo_path"] == str(Path(__file__).resolve().parents[1])
            assert created_payload["thread"]["metadata"]["agent_lane"] == "manual_paste"

            queued = client.post(
                f"/api/mcharness/sessions/{session_id}/queue",
                json={
                    "title": "Inspect git and tests",
                    "prompt": "Review the current worktree, summarize the diff, and return manual evidence.",
                    "target_role": "reviewer",
                    "file_scope": ["src/warden/api.py", "web/warden/app.js"],
                    "forbidden_file_scope": ["_mctable/**"],
                    "evidence_required": ["Transcript pasted back.", "Git status captured."],
                    "acceptance_checks": ["Evidence is explicit.", "No arbitrary shell execution."],
                },
            )
            assert queued.status_code == 200, queued.text
            queue_item_id = queued.json()["queue_item_id"]

            exported = client.post(
                f"/api/mcharness/sessions/{session_id}/prompt-export",
                json={"queue_item_id": queue_item_id, "mark_sent": True},
            )
            assert exported.status_code == 200, exported.text
            prompt_text = exported.json()["prompt_text"]
            for snippet in [
                "# McHarness Bounded Minion Prompt",
                f"- Session id: {session_id}",
                f"- Captain run id: {run_id}",
                f"- Queue item id: {queue_item_id}",
                "## Safety constraints",
                "## Files or areas to inspect",
                "## Acceptance tests",
                "## Required final proof format",
            ]:
                assert snippet in prompt_text

            manual_result = client.post(
                f"/api/mcharness/sessions/{session_id}/manual-result",
                json={
                    "summary": "Manual transcript and repo evidence captured from the selected lane.",
                    "transcript": "Operator pasted the worker transcript here.\nIt includes findings and next steps.",
                    "source_ref": "manual://codex-pasteback",
                    "verdict": "passed",
                    "complete_assignment": True,
                    "git_status": " M src/warden/api.py",
                    "git_diff_summary": " src/warden/api.py | 12 ++++++++++--",
                    "test_output": "2 passed in 0.42s",
                },
            )
            assert manual_result.status_code == 200, manual_result.text

            rejected = client.post(
                f"/api/mcharness/sessions/{session_id}/gate-decision",
                json={"decision": "rejected", "note": "Need a clearer transcript before continuation."},
            )
            assert rejected.status_code == 200, rejected.text

            approved = client.post(
                f"/api/mcharness/sessions/{session_id}/gate-decision",
                json={"decision": "approved", "note": "Transcript and evidence are sufficient."},
            )
            assert approved.status_code == 200, approved.text

            live_git = client.get(f"/api/mcharness/sessions/{session_id}/git-status")
            assert live_git.status_code == 200
            git_payload = live_git.json()
            assert git_payload["repo_path"] == str(Path(__file__).resolve().parents[1])
            assert "git_status" in git_payload
            assert "git_diff_summary" in git_payload

            artifacts = client.get(f"/api/mcharness/sessions/{session_id}/artifacts")
            assert artifacts.status_code == 200
            artifact_rows = artifacts.json()["artifacts"]
            kinds = {item["kind"] for item in artifact_rows}
            assert "prompt_export" in kinds
            assert "manual_result" in kinds
            assert "git_status" in kinds
            assert "git_diff_summary" in kinds
            assert "test_output" in kinds
            assert "evidence" in kinds
            assert "gate_decision" in kinds
            assert "run_summary" in kinds

        with TestClient(app) as reloaded_client:
            artifacts = reloaded_client.get(f"/api/mcharness/sessions/{session_id}/artifacts")
            assert artifacts.status_code == 200
            assert artifacts.json()["artifacts"]
    finally:
        _reset_runtime_state()