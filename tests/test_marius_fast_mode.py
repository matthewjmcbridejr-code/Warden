import pytest
import os
from unittest.mock import patch, AsyncMock
from src.marius.provider_gateway import ProviderGateway

@pytest.mark.anyio
async def test_chat_mode_fast_limits():
    with patch.dict(os.environ, {"MARIUS_CHAT_MODE": "fast"}):
        gateway = ProviderGateway()
        assert gateway.max_brain_records == 2
        assert gateway.max_brain_chars == 800

@pytest.mark.anyio
async def test_chat_mode_deep_limits():
    with patch.dict(os.environ, {"MARIUS_CHAT_MODE": "deep"}):
        gateway = ProviderGateway()
        assert gateway.max_brain_records == 6
        assert gateway.max_brain_chars == 3500

@pytest.mark.anyio
async def test_brain_skipped_for_simple_prompts():
    gateway = ProviderGateway()
    gateway.brain_context_enabled = True
    
    with patch("src.marius.provider_gateway.build_brain_context_pack") as mock_build:
        with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = {"choices": [{"message": {"content": "Hi"}}]}
            
            # Simple "hello" should skip brain
            await gateway.chat("hello")
            assert not mock_build.called

@pytest.mark.anyio
async def test_brain_forced_for_keywords():
    gateway = ProviderGateway()
    gateway.brain_context_enabled = True
    
    with patch("src.marius.provider_gateway.build_brain_context_pack") as mock_build:
        mock_build.return_value = {"context_text": "context", "record_ids": []}
        with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = {"choices": [{"message": {"content": "Answer"}}]}
            
            # "priorities" should trigger brain
            await gateway.chat("What are my priorities?")
            assert mock_build.called
