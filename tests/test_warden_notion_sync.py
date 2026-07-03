import json
from pathlib import Path

from warden import notion_sync


def write_task(board_root: Path, status: str, task_id: str, payload: dict):
    dest = board_root / "tasks" / status
    dest.mkdir(parents=True, exist_ok=True)
    data = {"task_id": task_id, "status": status, **payload}
    (dest / f"{task_id}.json").write_text(json.dumps(data), encoding="utf-8")


def test_dry_run_works_without_notion_env(tmp_path, monkeypatch):
    for name in notion_sync.NOTION_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    write_task(tmp_path, "queued", "task-1", {"title": "Sync candidate", "description": "Send to inbox"})

    result = notion_sync.sync_candidates_dry_run(tmp_path)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_enabled"] is False
    assert result["would_create_count"] == 1
    assert result["would_create"][0]["title"] == "Sync candidate"


def test_board_task_maps_to_notion_candidate_payload(tmp_path):
    write_task(
        tmp_path,
        "running",
        "task-2",
        {
            "title": "Implement dry run",
            "description": "Preview Notion writes safely",
            "project_id": "warden",
            "priority": "high",
            "agent": "codex",
            "repo_path": "/home/example/repo",
            "branch": "feat/notion-sync",
        },
    )

    [candidate] = notion_sync.build_candidate_tasks_from_board(tmp_path)

    assert candidate["warden_task_id"] == "task-2"
    assert candidate["project"] == "warden"
    assert candidate["status"] == "candidate"
    assert candidate["source"] == "warden"
    assert candidate["type"] == "agent_task"
    assert candidate["priority"] == "high"
    assert candidate["ai_summary"] == "Preview Notion writes safely"
    assert candidate["proof_status"] == "proof_needed"
    assert candidate["agent"] == "codex"
    assert candidate["repo_path"] == "/home/example/repo"
    assert candidate["branch"] == "feat/notion-sync"
    assert candidate["source_link"] == "warden://task/task-2"


def test_duplicate_detection_by_task_id():
    candidate = {"warden_task_id": "task-3", "title": "A", "project": "Warden", "source": "warden"}
    existing = [{"warden_task_id": "task-3", "title": "Old", "project": "Warden", "source": "warden"}]

    result = notion_sync.dedupe_candidates([candidate], existing_candidates=existing)

    assert result["unique"] == []
    assert result["skipped"][0]["skip_reason"] == "duplicate"


def test_duplicate_detection_by_normalized_fallback_key():
    first = {"title": "Ship Command Deck", "project": "Warden", "source": "warden"}
    second = {"title": "ship command deck", "project": "warden", "source": "warden"}

    result = notion_sync.dedupe_candidates([first, second])

    assert len(result["unique"]) == 1
    assert len(result["skipped"]) == 1


def test_write_is_blocked_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("WARDEN_NOTION_WRITE_ENABLED", raising=False)
    write_task(tmp_path, "queued", "task-4", {"title": "Blocked write"})

    result = notion_sync.sync_candidates_write(tmp_path)

    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["dry_run"] is True
    assert result["preview"]["would_create_count"] == 1


def test_status_redacts_secret_values(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "secret-token-value")
    monkeypatch.setenv("NOTION_MASTER_INBOX_DATABASE_ID", "secret-database-id")

    result = notion_sync.notion_sync_status()
    dumped = json.dumps(result)

    assert result["configured"]["NOTION_API_KEY"] is True
    assert result["configured"]["NOTION_MASTER_INBOX_DATABASE_ID"] is True
    assert "secret-token-value" not in dumped
    assert "secret-database-id" not in dumped


def test_proof_status_mapping():
    assert notion_sync.proof_status_for_task({"status": "completed"}) == "proof_needed"
    assert notion_sync.proof_status_for_task({"status": "completed", "proof": {"summary": "done"}}) == "verified"
    assert notion_sync.proof_status_for_task({"status": "failed"}) == "failed"
    assert notion_sync.proof_status_for_task({"status": "running", "failure": {"blocker": "missing approval"}}) == "blocked"
    assert notion_sync.proof_status_for_task({"status": "queued", "handoff": {"to_agent": "claude"}}) == "handoff"


def test_empty_board_returns_no_candidates(tmp_path):
    result = notion_sync.sync_candidates_dry_run(tmp_path)

    assert result["ok"] is True
    assert result["candidates_found"] == 0
    assert result["would_create"] == []
    assert result["would_skip"] == []
