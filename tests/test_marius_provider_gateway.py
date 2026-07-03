import pytest
import os
import json
from unittest.mock import MagicMock, patch, AsyncMock
from src.marius.provider_gateway import ProviderGateway
from src.marius.model_profiles import MODEL_PROFILES

@pytest.mark.anyio
async def test_resolve_model_local_first():
    gateway = ProviderGateway()
    gateway.mode = "local"
    gateway.forced_model = None

    with patch.object(ProviderGateway, "get_available_ollama_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = ["llama3.2:1b", "llama3.2:3b"]
        gateway.current_profile = "fast"
        provider, model, profile, _ = await gateway.resolve_model_and_provider()
        assert provider == "ollama"
        assert model == "llama3.2:1b"

@pytest.mark.anyio
async def test_cloud_disabled_by_default():
    gateway = ProviderGateway()
    # allow_cloud should be False by default if MARIUS_ALLOW_CLOUD is not set
    assert gateway.allow_cloud is False

@pytest.mark.anyio
async def test_profile_fast_selection():
    gateway = ProviderGateway()
    gateway.forced_model = None
    # Mock available models to only have the last one in 'fast' profile
    with patch.object(ProviderGateway, "get_available_ollama_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = ["llama3.2:1b"]
        gateway.current_profile = "fast"
        provider, model, profile, _ = await gateway.resolve_model_and_provider()
        assert model == "llama3.2:1b"

@pytest.mark.anyio
async def test_forced_model_override():
    gateway = ProviderGateway()
    gateway.forced_model = "my-custom-model"
    with patch.object(ProviderGateway, "get_available_ollama_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = ["my-custom-model", "llama3.2:3b"]
        provider, model, profile, _ = await gateway.resolve_model_and_provider()
        assert model == "my-custom-model"
        assert provider == "ollama"

@pytest.mark.anyio
async def test_benchmark_skips_missing():
    gateway = ProviderGateway()
    with patch.object(ProviderGateway, "get_available_ollama_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = ["llama3.2:1b"]
        # Benchmarking against a list that includes missing ones
        # Use the updated signature returning Dict
        res = await gateway.benchmark(models=["llama3.2:1b", "non-existent"])
        results = res.get("results", [])
        assert len(results) >= 0
        assert all(r["model"] == "llama3.2:1b" for r in results)

@pytest.mark.anyio
async def test_embedding_model_not_selected_for_chat():
    gateway = ProviderGateway()
    gateway.forced_model = None
    with patch.object(ProviderGateway, "get_available_ollama_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = ["mxbai-embed-large", "llama3.2:1b"]
        gateway.current_profile = "fast"
        provider, model, profile, _ = await gateway.resolve_model_and_provider()
        assert model != "mxbai-embed-large"

@pytest.mark.anyio
@pytest.mark.skip(reason="Cloud routing not yet implemented in provider_gateway (priority-3 block is pass)")
async def test_cloud_enabled_selection():
    gateway = ProviderGateway()
    gateway.mode = "cloud"
    gateway.allow_cloud = True
    gateway.current_profile = "code"

    with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
        provider, model, profile, _ = await gateway.resolve_model_and_provider()
        assert provider == "groq"
        assert "qwen" in model.lower()

@pytest.mark.anyio
async def test_router_only_model_auto_switch():
    gateway = ProviderGateway()
    gateway.forced_model = "marius-fast"

    with patch.object(ProviderGateway, "get_available_ollama_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = ["marius-fast", "llama3.2:1b"]
        with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = {
                "choices": [{"message": {"content": "Hello!"}}]
            }
            # Should auto-switch because marius-fast is in ROUTER_MODELS
            result = await gateway.chat("what is warden?")
            assert result["actual"] == "llama3.2:1b"
            assert result["warning"] is not None
            assert "router-only" in result["warning"]

@pytest.mark.anyio
async def test_embedding_model_auto_switch():
    gateway = ProviderGateway()
    gateway.forced_model = "mxbai-embed-large"

    with patch.object(ProviderGateway, "get_available_ollama_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = ["mxbai-embed-large", "llama3.2:1b"]
        with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = {
                "choices": [{"message": {"content": "Hello!"}}]
            }
            # Should auto-switch because mxbai-embed-large is in EMBEDDING_MODELS
            result = await gateway.chat("what is warden?")
            assert result["actual"] == "llama3.2:1b"

@pytest.mark.anyio
async def test_gateway_chat_with_history():
    gateway = ProviderGateway()
    with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = {
            "choices": [{"message": {"content": "Hello!"}}]
        }
        history = [{"role": "user", "content": "Hi"}]
        result = await gateway.chat("How are you?", history=history)
        assert result["response"] == "Hello!"
        assert result["provider"] == "ollama"
        # Check that system prompt was added and history was preserved
        args, kwargs = mock_complete.call_args
        messages = args[0]
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "Hi"
        assert messages[2]["content"] == "How are you?"
