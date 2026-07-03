import pytest
import os
from scripts.marius_chat import parse_command, ApiClient, MariusCLI, ConfigManager
from unittest.mock import MagicMock, patch

def test_parse_command_chat():
    cmd, args = parse_command("Hello Marius")
    assert cmd is None
    assert args == ["Hello Marius"]

def test_parse_command_aliases():
    assert parse_command("/s")[0] == "status"
    assert parse_command("/p")[0] == "projects"
    assert parse_command("/lo")[0] == "leftoff"
    assert parse_command("/r query")[0] == "recall"
    assert parse_command("/m")[0] == "model"
    assert parse_command("/q")[0] == "exit"
    assert parse_command("/h")[0] == "help"

def test_parse_command_natural_memory():
    cmd, args = parse_command("remember that Marius is cool")
    assert cmd == "remember"
    assert args == ["general", "Marius is cool"]
    
    cmd, args = parse_command("note that this is important")
    assert cmd == "remember"
    assert args == ["general", "this is important"]

def test_parse_command_remember_category():
    cmd, args = parse_command("/remember project: Finish the CLI")
    assert cmd == "remember"
    assert args == ["project", "Finish the CLI"]

@patch("requests.get")
def test_api_client_probe(mock_get):
    mock_get.side_effect = [
        MagicMock(status_code=404),
        MagicMock(status_code=200)
    ]
    client = ApiClient()
    res = client.probe(["http://bad", "http://good"])
    assert res == "http://good"

def test_config_manager(tmp_path):
    config_file = tmp_path / "config.json"
    mgr = ConfigManager(str(config_file))
    mgr.set("api_base", "http://localhost:8126")
    
    mgr2 = ConfigManager(str(config_file))
    assert mgr2.get("api_base") == "http://localhost:8126"

def test_cli_session_stats():
    with patch("scripts.marius_chat.ApiClient.get_chat") as mock_chat:
        mock_chat.return_value = {"response": "Hi", "provider": "test"}
        cli = MariusCLI("http://localhost:8126")
        cli.run_command("Hello")
        assert cli.session_stats["messages_sent"] == 1
        
    with patch("scripts.marius_chat.ApiClient.save_memory") as mock_save:
        mock_save.return_value = {"status": "saved"}
        cli.run_command("/remember test")
        assert cli.session_stats["memory_writes"] == 1

def test_cli_api_command():
    cli = MariusCLI("http://localhost:8126")
    with patch("scripts.marius_chat.ApiClient.get_health") as mock_health:
        mock_health.return_value = True
        cli.run_command("/api http://localhost:9999")
        assert cli.client.api_base == "http://localhost:9999"
        assert cli.config.get("api_base") == "http://localhost:9999"

@patch("scripts.marius_chat.ApiClient.get_status")
def test_cli_session_command(mock_status, capsys):
    mock_status.return_value = {
        "model_backend": {
            "active_provider": "ollama",
            "configured_model": "llama3"
        }
    }
    cli = MariusCLI("http://localhost:8126")
    cli.run_command("/session")
    captured = capsys.readouterr()
    assert "API Base: http://localhost:8126" in captured.out
    assert "Provider: ollama" in captured.out
    assert "Messages Sent: 0" in captured.out
