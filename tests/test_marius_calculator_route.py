import pytest
from src.marius.calculator import safe_calc, is_math_query
from src.marius.provider_gateway import ProviderGateway
from unittest.mock import patch, AsyncMock

def test_is_math_query():
    assert is_math_query("what is 2 + 2") is True
    assert is_math_query("10 * 5 / 2") is True
    assert is_math_query("hello world") is False
    assert is_math_query("what is the weather?") is False

def test_safe_calc():
    assert safe_calc("2 + 2") == "4"
    assert safe_calc("10 * 5") == "50"
    assert safe_calc("2 ^ 3") == "8"
    assert safe_calc("(10 + 2) / 4") == "3.0"
    # Unsafe should return None
    assert safe_calc("import os") is None
    assert safe_calc("__import__('os').system('ls')") is None

@pytest.mark.anyio
async def test_chat_uses_calculator_route():
    gateway = ProviderGateway()
    # Math query should NOT call any provider
    with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
        res = await gateway.chat("what is 5 * 5")
        assert res["response"] == "25"
        assert res["provider"] == "local_calculator"
        assert not mock_complete.called
