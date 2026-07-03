import pytest
import os
from unittest.mock import MagicMock, patch
from src.marius.google_search_provider import GoogleAgentSearchProvider

@patch("src.marius.google_search_provider.os.getenv")
def test_google_provider_status_detailed(mock_getenv):
    # Setup mock environment
    env = {
        "MARIUS_SEARCH_PROVIDER": "google",
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_AGENT_SEARCH_ENGINE_ID": "test-engine",
        "GOOGLE_AGENT_SEARCH_LOCATION": "global",
        "GOOGLE_AGENT_SEARCH_SERVING_CONFIG": "custom_config"
    }
    mock_getenv.side_effect = env.get
    
    with patch("google.cloud.discoveryengine_v1.SearchServiceClient") as mock_client:
        provider = GoogleAgentSearchProvider()
        status = provider.status()
        assert status["requested_provider"] == "google"
        assert status["actual_provider"] == "google"
        assert status["engine_id"] == "test-engine"
        assert "custom_config" in status["serving_config_path"]
        assert status["ready"] is True

@patch("src.marius.google_search_provider.os.getenv")
def test_google_provider_search_success_label(mock_getenv):
    env = {
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_AGENT_SEARCH_ENGINE_ID": "test-engine"
    }
    mock_getenv.side_effect = env.get
    
    with patch("google.cloud.discoveryengine_v1.SearchServiceClient") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.serving_config_path.return_value = "projects/test/locations/global/collections/default_collection/engines/test/servingConfigs/default"
        
        # Mock search response
        mock_result = MagicMock()
        mock_result.document.id = "doc1"
        mock_result.document.derived_struct_data = {
            "title": "Google Doc",
            "snippets": [{"snippet": "Google content"}]
        }
        mock_client.search.return_value = [mock_result]
        
        provider = GoogleAgentSearchProvider()
        results = provider.search("query")
        
        assert len(results) == 1
        assert results[0]["provider"] == "google"
        assert "Google Doc" in results[0]["title"]

@patch("src.marius.google_search_provider.os.getenv")
def test_google_provider_filters_disabled_by_default(mock_getenv):
    env = {
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_AGENT_SEARCH_ENGINE_ID": "test-engine"
    }
    mock_getenv.side_effect = env.get
    
    with patch("google.cloud.discoveryengine_v1.SearchServiceClient") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.serving_config_path.return_value = "projects/test/locations/global/collections/default_collection/engines/test/servingConfigs/default"
        mock_client.search.return_value = []
        
        provider = GoogleAgentSearchProvider()
        provider.search("query", project="grademy")
        
        # Verify that filter was NOT passed to the client
        assert mock_client.search.called
        args, kwargs = mock_client.search.call_args
        request = args[0]
        assert request.filter == ""

@patch("src.marius.google_search_provider.os.getenv")
def test_google_provider_filters_enabled_via_env(mock_getenv):
    env = {
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_AGENT_SEARCH_ENGINE_ID": "test-engine",
        "GOOGLE_AGENT_SEARCH_ENABLE_METADATA_FILTERS": "1"
    }
    mock_getenv.side_effect = env.get
    
    with patch("google.cloud.discoveryengine_v1.SearchServiceClient") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.serving_config_path.return_value = "projects/test/locations/global/collections/default_collection/engines/test/servingConfigs/default"
        mock_client.search.return_value = []
        
        provider = GoogleAgentSearchProvider()
        provider.search("query", project="grademy")
        
        # Verify that filter WAS passed to the client
        assert mock_client.search.called
        args, kwargs = mock_client.search.call_args
        request = args[0]
        assert 'project: ANY("grademy")' in request.filter

@patch("src.marius.google_search_provider.os.getenv")
def test_google_provider_error_reporting(mock_getenv):
    env = {
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_AGENT_SEARCH_ENGINE_ID": "test-engine"
    }
    mock_getenv.side_effect = env.get
    
    with patch("google.cloud.discoveryengine_v1.SearchServiceClient") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.serving_config_path.return_value = "projects/test/locations/global/collections/default_collection/engines/test/servingConfigs/default"
        mock_client.search.side_effect = Exception("Deadline Exceeded")
        
        provider = GoogleAgentSearchProvider()
        results = provider.search("query")
        
        assert len(results) == 1
        assert results[0]["project"] == "error"
        assert "Deadline Exceeded" in results[0]["snippet"]
        assert results[0]["provider"] == "local fallback"

@patch("src.marius.google_search_provider.os.getenv")
def test_google_provider_fallback_reason_visible(mock_getenv):
    mock_getenv.return_value = None
    with patch("google.cloud.discoveryengine_v1.SearchServiceClient", side_effect=ImportError()):
        provider = GoogleAgentSearchProvider()
        status = provider.status()
        assert status["ready"] is False
        assert "package not installed" in status["fallback_reason"]

def test_mctable_search_config_accepted():
    with patch.dict(os.environ, {
        "GOOGLE_AGENT_SEARCH_ENGINE_ID": "mctable-search",
        "GOOGLE_AGENT_SEARCH_DATA_STORE_ID": "mctable-codebase",
        "GOOGLE_CLOUD_PROJECT": "test-project"
    }):
        with patch("google.cloud.discoveryengine_v1.SearchServiceClient"):
            provider = GoogleAgentSearchProvider()
            assert provider.engine_id == "mctable-search"
            assert provider.data_store_id == "mctable-codebase"
            assert provider.status()["ready"] is True
