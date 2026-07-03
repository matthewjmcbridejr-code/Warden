import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from src.marius.provider_gateway import ProviderGateway

@pytest.mark.anyio
async def test_chat_injects_brain_context():
    gateway = ProviderGateway()
    gateway.brain_context_enabled = True
    
    with patch("src.marius.provider_gateway.build_brain_context_pack") as mock_build:
        mock_build.return_value = {
            "context_text": "MARIUS BRAIN CONTEXT: * [rec1] Matt Profile — personal — snippet",
            "record_ids": ["rec1"]
        }
        
        with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = {"choices": [{"message": {"content": "Answer."}}]}
            
            await gateway.chat("what is my working style?")
            
            # Check that system prompt contains brain context
            args, kwargs = mock_complete.call_args
            messages = args[0]
            system_msg = next(m["content"] for m in messages if m["role"] == "system")
            assert "MARIUS BRAIN CONTEXT" in system_msg
            assert "rec1" in system_msg

@pytest.mark.anyio
async def test_chat_respects_brain_disabled_toggle():
    gateway = ProviderGateway()
    gateway.brain_context_enabled = False
    
    with patch("src.marius.provider_gateway.build_brain_context_pack") as mock_build:
        with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = {"choices": [{"message": {"content": "Answer."}}]}
            
            await gateway.chat("test")
            
            assert not mock_build.called
            args, kwargs = mock_complete.call_args
            messages = args[0]
            system_msg = next(m["content"] for m in messages if m["role"] == "system")
            assert "MARIUS BRAIN CONTEXT" not in system_msg
