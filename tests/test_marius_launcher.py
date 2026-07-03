import pytest
import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from scripts.marius_chat import parse_command, ApiClient, MariusCLI, ConfigManager, DEFAULT_API_BASE, PID_PATH

def test_parse_command_chat():
    cmd, args = parse_command("Hello Marius")
    assert cmd is None
    assert args == ["Hello Marius"]

def test_parse_command_natural_memory():
    cmd, args = parse_command("remember that Marius is cool")
    assert cmd == "remember"
    assert args == ["general", "Marius is cool"]

def test_api_client_health_url():
    client = ApiClient("http://localhost:6969/api/mcharness/marius")
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": "OK"}
        assert client.get_health() is True
        mock_get.assert_called_once_with("http://localhost:6969/api/mcharness/marius/health", params=None, timeout=2)

def test_config_manager_load_save(tmp_path):
    config_file = tmp_path / "config.json"
    mgr = ConfigManager(config_file)
    mgr.set("api_base", "http://localhost:1234")
    
    mgr2 = ConfigManager(config_file)
    assert mgr2.get("api_base") == "http://localhost:1234"

@patch("subprocess.Popen")
@patch("scripts.marius_chat.ApiClient.get_health")
def test_cli_start_server(mock_health, mock_popen, tmp_path):
    # Setup mocks
    mock_health.side_effect = [False, True] # First check fail, second (after start) success
    mock_popen.return_value.pid = 1234
    
    with patch("scripts.marius_chat.PID_PATH", tmp_path / "marius.pid"):
        with patch("scripts.marius_chat.LOG_PATH", tmp_path / "marius.log"):
            cli = MariusCLI(DEFAULT_API_BASE)
            cli.start_server()
            
            assert mock_popen.called
            assert (tmp_path / "marius.pid").read_text() == "1234"

@patch("os.killpg")
@patch("os.getpgid")
def test_cli_stop_server(mock_getpgid, mock_killpg, tmp_path):
    pid_file = tmp_path / "marius.pid"
    pid_file.write_text("1234")
    mock_getpgid.return_value = 5678
    
    with patch("scripts.marius_chat.PID_PATH", pid_file):
        cli = MariusCLI(DEFAULT_API_BASE)
        cli.stop_server()
        
        mock_killpg.assert_called_once_with(5678, signal.SIGTERM)
        assert not pid_file.exists()

def test_cli_doctor_output(capsys):
    cli = MariusCLI(DEFAULT_API_BASE)
    with patch("scripts.marius_chat.ApiClient.get_health") as mock_health:
        mock_health.return_value = False
        cli.doctor()
        captured = capsys.readouterr()
        assert "Marius Doctor Diagnostics" in captured.out
        assert "Health Check: FAILED" in captured.out

def test_discovery_resolution(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"api_base": "http://stale:8126"}')
    
    # We want to test the logic in __main__ essentially
    # But since it's hard to test __main__ directly, we'll verify the pieces
    
    with patch("scripts.marius_chat.CONFIG_PATH", config_file):
        config = ConfigManager(config_file)
        api_base = None or os.getenv("MARIUS_API_BASE") or config.get("api_base") or DEFAULT_API_BASE
        assert api_base == "http://stale:8126"
