import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from src.marius.brain_ingest import BrainIngest

@pytest.mark.anyio
async def test_add_url_ingests_content(tmp_path):
    bi = BrainIngest()
    bi.data_path = tmp_path / "records.jsonl"
    
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.text = "<html><title>Test Page</title><body>This is the body text about McServer.</body></html>"
    mock_resp.status_code = 200
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await bi.add_url("https://example.com/test", project="research")
        assert res["ok"]
        assert res["record"]["title"] == "Test Page"
        assert "McServer" in res["record"]["text"]
        assert res["record"]["domain"] == "example.com"

@pytest.mark.anyio
async def test_add_url_rejects_secrets(tmp_path):
    bi = BrainIngest()
    bi.data_path = tmp_path / "records.jsonl"
    
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.text = "<html><body>My secret is password=123</body></html>"
    mock_resp.status_code = 200
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await bi.add_url("https://example.com/secret")
        assert not res["ok"]
        assert "rejected" in res["error"]
