import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from src.marius.config import Config
from src.marius.provider_gateway import ProviderGateway

@pytest.fixture
def mock_config(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"model": "qwen3:0.6b", "profile": "fast"}))
    return config_file

def test_config_persistence(tmp_path):
    config_file = tmp_path / "config.json"
    cfg = Config(config_file)
    cfg.set("model", "llama3.2:1b")
    
    # Reload and check
    cfg2 = Config(config_file)
    assert cfg2.get("model") == "llama3.2:1b"

@pytest.mark.anyio
async def test_provider_gateway_uses_config_model(mock_config):
    with patch("src.marius.config.CONFIG_PATH", mock_config):
        gateway = ProviderGateway()
        # Mock available models in Ollama
        with patch.object(ProviderGateway, "get_available_ollama_models", return_value=["qwen3:0.6b"]):
            provider, model, profile, fallback = await gateway.resolve_model_and_provider()
            assert model == "qwen3:0.6b"
            assert provider == "ollama"

@pytest.mark.anyio
async def test_provider_gateway_fails_if_forced_missing(mock_config):
    with patch("src.marius.config.CONFIG_PATH", mock_config):
        gateway = ProviderGateway()
        # qwen3:0.6b is configured but NOT installed
        with patch.object(ProviderGateway, "get_available_ollama_models", return_value=["llama3.2:1b"]):
            provider, model, profile, fallback = await gateway.resolve_model_and_provider()
            assert provider == "fallback"
            assert "not installed" in fallback
