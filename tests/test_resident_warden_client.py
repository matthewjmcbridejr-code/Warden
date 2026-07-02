"""WardenClient tests: mocked status/sessions, session tail capped to N lines."""
from unittest.mock import patch

from src.warden.resident.warden_client import DEFAULT_SESSION_TAIL_LINES, WardenClient


def test_list_agents_mocked():
    client = WardenClient()
    fake_agents = [{"id": "codex_cli", "name": "Codex CLI"}]
    with patch("src.warden.agent_registry.list_all_agents", return_value=fake_agents):
        result = client.list_agents()
    assert result["ok"] is True
    assert result["key_fields"]["count"] == 1


def test_list_agents_handles_failure():
    client = WardenClient()
    with patch("src.warden.agent_registry.list_all_agents", side_effect=RuntimeError("boom")):
        result = client.list_agents()
    assert result["ok"] is False


def test_list_sessions_mocked():
    client = WardenClient()

    def fake_iter(status):
        if status == "claimed":
            yield {"task_id": "t1", "title": "Task 1", "agent": "codex", "updated_at": "now"}, None

    with patch("src.warden.agent_dispatcher._iter_tasks_by_status", side_effect=fake_iter):
        result = client.list_sessions()
    assert result["ok"] is True
    assert result["key_fields"]["count"] == 1


def test_session_tail_capped(tmp_path):
    client = WardenClient()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "t1_abcd1234.log"
    lines = [f"line {i}" for i in range(200)]
    log_file.write_text("\n".join(lines))

    with patch("src.warden.agent_dispatcher.load_config", return_value={"log_dir": str(log_dir)}):
        result = client.session_tail("t1", max_lines=20)
    assert result["ok"] is True
    assert result["key_fields"]["lines"] == 20
    assert len(result["raw"]) == 20
    assert result["raw"][-1] == "line 199"


def test_session_tail_default_cap_respected(tmp_path):
    client = WardenClient()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "t2_abcd1234.log"
    lines = [f"line {i}" for i in range(200)]
    log_file.write_text("\n".join(lines))
    with patch("src.warden.agent_dispatcher.load_config", return_value={"log_dir": str(log_dir)}):
        result = client.session_tail("t2")
    assert result["key_fields"]["lines"] == DEFAULT_SESSION_TAIL_LINES


def test_session_tail_no_log_found(tmp_path):
    client = WardenClient()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    with patch("src.warden.agent_dispatcher.load_config", return_value={"log_dir": str(log_dir)}):
        result = client.session_tail("missing")
    assert result["ok"] is False


def test_status_combines_agents_and_sessions():
    client = WardenClient()
    with patch.object(client, "list_agents", return_value={"ok": True, "key_fields": {"count": 2}}), \
         patch.object(client, "list_sessions", return_value={"ok": True, "key_fields": {"count": 1}}):
        result = client.status()
    assert result["key_fields"]["agents"] == 2
    assert result["key_fields"]["sessions"] == 1


def test_stop_session_no_match_found():
    client = WardenClient()
    with patch.object(client, "list_sessions", return_value={"raw": []}):
        result = client.stop_session("some session")
    assert result["ok"] is False
    assert "no active session matched" in result["short_summary"].lower()


def test_stop_session_match_returns_dry_run():
    client = WardenClient()
    sessions = {"raw": [{"task_id": "t1", "title": "Deploy site"}]}
    with patch.object(client, "list_sessions", return_value=sessions):
        result = client.stop_session("deploy")
    assert result["ok"] is False
    assert "executor not implemented" in result["short_summary"]
    assert result["key_fields"]["dry_run"] is True
