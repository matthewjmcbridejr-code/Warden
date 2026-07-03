import pytest
import os
import json
from unittest.mock import MagicMock, patch, AsyncMock
from src.marius.router import chat_completion, test_ollama_model as router_test_ollama_model
from src.marius.api import chat, model_test, ChatRequest
import requests

@patch("src.marius.router.requests.post")
def test_chat_completion_timeout_uses_correct_val(mock_post):
    os.environ["MARIUS_OLLAMA_CHAT_TIMEOUT"] = "45"
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"message": {"content": "hi"}}
    
    chat_completion("hello")
    
    args, kwargs = mock_post.call_args
    assert kwargs["timeout"] == 45

@patch("src.marius.router.requests.post")
def test_chat_completion_success(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"message": {"content": "The sky is blue because of Rayleigh scattering."}}
    
    response, provider, model = chat_completion("Why is the sky blue?")
    assert provider == "ollama"
    assert "Rayleigh scattering" in response

@patch("src.marius.router.requests.post")
def test_chat_completion_timeout_fallback(mock_post):
    mock_post.side_effect = requests.exceptions.Timeout()
    
    response, provider, model = chat_completion("test")
    assert provider == "fallback"
    assert "ollama_timeout" in response

@patch("src.marius.router.requests.post")
def test_chat_completion_connection_error(mock_post):
    mock_post.side_effect = requests.exceptions.ConnectionError()
    
    response, provider, model = chat_completion("test")
    assert provider == "fallback"
    assert "connection_refused" in response

@patch("src.marius.router.requests.post")
def test_chat_completion_model_not_found(mock_post):
    mock_post.return_value = MagicMock(status_code=404)
    
    response, provider, model = chat_completion("test", model="non-existent")
    assert provider == "fallback"
    assert "model_not_found" in response

@patch("src.marius.router.requests.post")
def test_chat_completion_bad_response(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    
    response, provider, model = chat_completion("test")
    assert provider == "fallback"
    assert "ollama_bad_response" in response

@patch("src.marius.router.requests.post")
def test_model_test_endpoint_success(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"message": {"content": "OK"}}
    
    res = router_test_ollama_model()
    assert res["ok"] is True
    assert res["provider"] == "ollama"
    assert "elapsed_ms" in res

@patch("src.marius.router.requests.post")
def test_model_test_endpoint_failure(mock_post):
    mock_post.side_effect = requests.exceptions.Timeout()
    
    res = router_test_ollama_model()
    assert res["ok"] is False
    assert res["reason"] == "timeout"

@pytest.mark.anyio
async def test_api_chat_endpoint():
    with patch("src.marius.api.gateway.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"response": "hi", "provider": "ollama", "model": "llama3"}
        req = ChatRequest(message="hello")
        res = await chat(req)
        assert res["response"] == "hi"
        assert res["provider"] == "ollama"

def test_api_model_test_endpoint():
    with patch("src.marius.api.test_ollama_model") as mock_tm:
        mock_tm.return_value = {"ok": True}
        res = model_test()
        assert res["ok"] is True

from scripts.marius_chat import ApiClient, MariusCLI

@patch("scripts.marius_chat.requests.post")
def test_cli_uses_long_timeout(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"response": "hi"}
    
    client = ApiClient("http://localhost:6969")
    client.get_chat("hello")
    
    args, kwargs = mock_post.call_args
    # Now uses 180s
    assert kwargs["timeout"] == 180

def test_once_and_repl_use_same_path():
    # Both call cli.run_command(line) -> handle_chat(msg) -> client.get_chat(msg)
    cli = MariusCLI("http://localhost:6969")
    with patch.object(ApiClient, "get_chat") as mock_get_chat:
        mock_get_chat.return_value = {"response": "hi"}
        
        # Test --once path
        cli.run_command("hello once")
        mock_get_chat.assert_called_with("hello once", brain_context=False)

        # Test REPL path
        cli.run_command("hello repl")
        mock_get_chat.assert_called_with("hello repl", brain_context=False)
