import pytest
import os
import shutil
from fastapi.testclient import TestClient
from pathlib import Path

# Set up test environment before imports
TEST_DATA_ROOT = Path("tests/marius_test_data")
os.environ["MARIUS_DATA_ROOT"] = str(TEST_DATA_ROOT)
os.environ["MCHARNESS_DATA_ROOT"] = str(TEST_DATA_ROOT)
os.environ["MARIUS_TELEGRAM_ENABLED"] = "0"

from src.warden.app import app
from src.marius.tools import redact_secrets

from unittest.mock import patch, MagicMock, AsyncMock

@pytest.fixture(autouse=True)
def setup_teardown():
    if TEST_DATA_ROOT.exists():
        shutil.rmtree(TEST_DATA_ROOT)
    TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    yield
    if TEST_DATA_ROOT.exists():
        shutil.rmtree(TEST_DATA_ROOT)

def test_marius_status_diagnostics():
    client = TestClient(app)
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"models": [{"name": "llama3.2:3b"}]}
        
        response = client.get("/api/mcharness/marius/status")
        assert response.status_code == 200
        data = response.json()
        assert "model_backend" in data
        diag = data["model_backend"]
        assert diag["ollama_reachable"] is True
        assert diag["configured_model"] == "llama3.2:3b"
        assert "llama3.2:3b" in diag["available_models"]

def test_marius_chat_success():
    client = TestClient(app)
    from src.marius.model_profiles import get_profile
    profile = get_profile("fast")
    complete_result = {
        "choices": [{"message": {"content": "I am Marius, your assistant."}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    }
    with patch("src.marius.provider_gateway.ProviderGateway.resolve_model_and_provider", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = ("ollama", "llama3.2:3b", profile, None)
        with patch("src.marius.providers.ollama.OllamaProvider.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = complete_result

            response = client.post("/api/mcharness/marius/chat", json={"message": "Who are you?"})
            assert response.status_code == 200
            data = response.json()
            assert data["provider"] == "ollama"
            assert "Marius" in data["response"]

def test_marius_health():
    client = TestClient(app)
    response = client.get("/api/mcharness/marius/health")
    assert response.status_code == 200
    assert response.json()["status"] == "OK"

def test_marius_status_redaction():
    client = TestClient(app)
    response = client.get("/api/mcharness/marius/status")
    assert response.status_code == 200
    data = response.json()
    assert "git" in data
    assert "services" in data
    
    # Verify redaction logic directly
    secret_text = "My key is sk-1234567890abcdef1234567890abcdef"
    redacted = redact_secrets(secret_text)
    assert "[REDACTED]" in redacted
    assert "sk-1234567890" not in redacted

def test_marius_chat_fallback():
    client = TestClient(app)
    # Ensure resolution fails
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Connection refused")
        response = client.post("/api/mcharness/marius/chat", json={"message": "hello"})
        assert response.status_code == 200
        assert "fallback" in response.json()["provider"]

def test_marius_memory_cycle():
    client = TestClient(app)
    # Remember
    rem_resp = client.post(
        "/api/mcharness/marius/memory/remember", 
        json={"content": "Marius is back", "category": "test"}
    )
    assert rem_resp.status_code == 200
    
    # Recall
    rec_resp = client.get("/api/mcharness/marius/memory/recall?q=Marius")
    assert rec_resp.status_code == 200
    results = rec_resp.json()
    assert len(results) > 0
    assert results[0]["content"] == "Marius is back"

def test_telegram_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MARIUS_TELEGRAM_ENABLED", raising=False)
    from src.marius.bot import start_bot
    # Should return None and not start a thread
    thread = start_bot()
    assert thread is None

def test_marius_projects():
    client = TestClient(app)
    response = client.get("/api/mcharness/marius/projects")
    assert response.status_code == 200
    projs = response.json()
    assert any(p["id"] == "warden" for p in projs)
    assert any(p["id"] == "hybrid" for p in projs)

def test_marius_handoff():
    client = TestClient(app)
    response = client.post(
        "/api/mcharness/marius/handoff/agent-prompt", 
        json={"target": "codex", "context": "Fixing bugs"}
    )
    assert response.status_code == 200
    assert "CODEX HANDOFF" in response.json()["prompt"]
