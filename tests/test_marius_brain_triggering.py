import pytest
import os
from unittest.mock import patch, MagicMock

def test_casual_chat_no_brain(capsys):
    from scripts.marius_chat import MariusCLI
    cli = MariusCLI("http://localhost:6969")
    cli.client.get_chat = MagicMock(return_value={"response": "hi", "provider": "local", "brain_context": {"enabled": False}})
    
    with patch.dict(os.environ, {}, clear=True):
        cli.handle_chat("hello")
        out = capsys.readouterr().out
        assert "brain context:" not in out
        # check what was passed to get_chat
        cli.client.get_chat.assert_called_with("hello", brain_context=False)

def test_brain_command_forces_brain():
    from scripts.marius_chat import MariusCLI
    cli = MariusCLI("http://localhost:6969")
    cli.client.get_chat = MagicMock(return_value={"response": "hi"})
    
    cli.handle_chat("hello", brain_override=True)
    cli.client.get_chat.assert_called_with("hello", brain_context=True)
