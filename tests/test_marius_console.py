import pytest
from scripts.marius_chat import MariusCLI
from unittest.mock import patch, MagicMock

def test_console_help(capsys):
    cli = MariusCLI("http://localhost:6969")
    with patch("builtins.input", side_effect=["/help", "/exit"]):
        cli.handle_console()
        captured = capsys.readouterr()
        assert "Console Commands" in captured.out
        assert "/model" in captured.out
        assert "/brain on|off" in captured.out

def test_console_brain_toggle(capsys):
    import os
    original = os.environ.get("MARIUS_BRAIN_CONTEXT")
    try:
        cli = MariusCLI("http://localhost:6969")
        with patch("builtins.input", side_effect=["/brain off", "/exit"]):
            cli.handle_console()
            assert os.environ.get("MARIUS_BRAIN_CONTEXT") == "0"

        with patch("builtins.input", side_effect=["/brain on", "/exit"]):
            cli.handle_console()
            assert os.environ.get("MARIUS_BRAIN_CONTEXT") == "1"
    finally:
        if original is None:
            os.environ.pop("MARIUS_BRAIN_CONTEXT", None)
        else:
            os.environ["MARIUS_BRAIN_CONTEXT"] = original
