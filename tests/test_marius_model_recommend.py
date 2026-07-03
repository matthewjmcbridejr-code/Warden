import pytest
from unittest.mock import patch, MagicMock

def test_model_recommend_buckets(capsys):
    from scripts.marius_chat import MariusCLI
    cli = MariusCLI("http://localhost:6969")
    cli.client.get_models = MagicMock(return_value={
        "available_ollama": ["qwen3:0.6b", "qwen2.5-coder:3b"]
    })
    
    cli.handle_model_recommend()
    out = capsys.readouterr().out
    assert "fast_console:" in out
    assert "Recommended: qwen3:0.6b" in out
    assert "daily_brain:" in out
    assert "Recommended: qwen2.5-coder:3b" in out
