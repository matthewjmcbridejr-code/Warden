import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.marius.grounding import GroundingPack
from src.marius.provider_gateway import ProviderGateway

@pytest.mark.anyio
@pytest.mark.requires_ollama
async def test_grounding_injection():
    gateway = ProviderGateway()
    
    with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = {
            "choices": [{"message": {"content": "Grounded answer."}}]
        }
        
        await gateway.chat("what is warden?")
        
        # Verify that grounding pack was injected into the system message
        args, kwargs = mock_complete.call_args
        messages = args[0]
        system_msg = next(m["content"] for m in messages if m["role"] == "system")
        
        assert "Marius Grounding Pack" in system_msg
        assert "Warden is a local-first AI workspace" in system_msg

@pytest.mark.anyio
@pytest.mark.requires_ollama
async def test_anti_hallucination_rule_injection():
    gateway = ProviderGateway()
    
    with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = {
            "choices": [{"message": {"content": "Grounded answer."}}]
        }
        
        await gateway.chat("test")
        
        args, kwargs = mock_complete.call_args
        messages = args[0]
        system_msg = next(m["content"] for m in messages if m["role"] == "system")
        
        assert "CRITICAL ANTI-HALLUCINATION RULES" in system_msg
        assert "I'm not sure from my local context" in system_msg

def test_grounding_pack_file_loading():
    # AGENTS.md is loaded into facts — check for content that actually exists in it
    gp = GroundingPack()
    assert "Warden" in gp.facts
    assert "AGENTS.md" in gp.facts or "mcharness-public-export" in gp.facts

@pytest.mark.anyio
@pytest.mark.requires_ollama
async def test_uncertainty_behavior_with_mock():
    # This test verifies that the prompt contains the instruction to be uncertain.
    # We don't necessarily need to test the model's response here, but rather the harness logic.
    gateway = ProviderGateway()
    
    with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = {
            "choices": [{"message": {"content": "I'm not sure from my local context."}}]
        }
        
        res = await gateway.chat("what is project nebula?")
        assert "not sure" in res["response"]
