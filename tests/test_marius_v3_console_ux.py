import pytest
import os
from unittest.mock import patch, MagicMock

def test_marius_v3_console_start(capsys):
    from scripts.marius_chat import MariusCLI
    cli = MariusCLI("http://localhost:6969")
    with patch("builtins.input", side_effect=["/exit"]):
        cli.handle_console()
        out = capsys.readouterr().out
        assert "Marius Operator Console v3" in out
        assert "commands: /help /model why /brain <q> /recall <q> /context <q> /think <q> /deep <q> /exit" in out

def test_console_think_command():
    from scripts.marius_chat import parse_command
    cmd, args = parse_command("/think hello")
    assert cmd == "think"
    assert args == ["hello"]

def test_console_deep_command():
    from scripts.marius_chat import parse_command
    cmd, args = parse_command("/deep hello")
    assert cmd == "deep"
    assert args == ["hello"]
