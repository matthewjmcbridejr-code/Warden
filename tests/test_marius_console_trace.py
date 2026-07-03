import pytest
from unittest.mock import patch, MagicMock

def test_console_trace_mode(capsys):
    from scripts.marius_chat import MariusCLI
    cli = MariusCLI("http://localhost:6969")
    cli.client.get_chat = MagicMock(return_value={
        "response": "Answer",
        "provider": "ollama",
        "actual": "qwen3:0.6b",
        "profile": "fast",
        "elapsed": 1.2,
        "brain_context": {"enabled": True, "record_ids": ["rec1", "rec2"]}
    })
    
    cli.handle_chat("hello", trace_mode=True)
    out = capsys.readouterr().out
    assert "[route] pending..." in out
    assert "[route] provider=ollama model=qwen3:0.6b profile=fast" in out
    assert "[brain] records=2 ids=rec1,rec2" in out
    assert "[done] 1.2s" in out
