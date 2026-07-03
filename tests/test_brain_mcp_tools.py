"""Tests for Warden Brain MCP tools."""
import json
import pytest
from src.warden.brain import google_provider, mirror


@pytest.fixture(autouse=True)
def clean():
    google_provider.set_search_client_factory(None)
    mirror.set_document_pusher(None)
    yield
    google_provider.set_search_client_factory(None)
    mirror.set_document_pusher(None)


def _get_tool(name):
    """Import and call a brain MCP tool function by name."""
    import src.warden.brain_mcp_server as mcp_mod
    # Tools are registered in the module-level mcp object
    # Find the wrapped function by name
    for tool_name, fn in mcp_mod.mcp._tool_manager._tools.items():
        if tool_name == name:
            return fn.fn
    raise KeyError(f"Tool not found: {name}")


def test_brain_mcp_tools_importable():
    import src.warden.brain_mcp_server as mod
    # All brain tool names should be registered
    tool_names = list(mod.mcp._tool_manager._tools.keys())
    assert "brain_status" in tool_names
    assert "brain_init_vault" in tool_names
    assert "brain_reindex" in tool_names
    assert "brain_search" in tool_names
    assert "brain_ask" in tool_names
    assert "brain_write_note" in tool_names
    assert "brain_google_status" in tool_names
    assert "brain_google_mirror" in tool_names
    assert "brain_mirror_status" in tool_names
    assert "brain_list_sources" in tool_names


def test_brain_mcp_status_returns_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    fn = _get_tool("brain_status")
    result = json.loads(fn())
    assert result["ok"] is True
    assert "local" in result["data"]
    assert "google" in result["data"]


def test_brain_mcp_init_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    fn = _get_tool("brain_init_vault")
    result = json.loads(fn())
    assert result["ok"] is True
    assert result["data"]["initialized"] is True


def test_brain_mcp_write_note(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    from src.warden.brain.vault import init_vault
    init_vault(vault_path=tmp_path)
    fn = _get_tool("brain_write_note")
    result = json.loads(fn(title="MCP Test Note", body="Some content for the MCP tool."))
    assert result["ok"] is True
    assert "path" in result["data"]


def test_brain_mcp_google_status_not_configured(monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_PROJECT_ID", raising=False)
    monkeypatch.delenv("WARDEN_GOOGLE_DISCOVERY_ENGINE_DATA_STORE_ID", raising=False)
    fn = _get_tool("brain_google_status")
    result = json.loads(fn())
    assert result["ok"] is True
    assert result["data"]["configured"] is False


def test_brain_mcp_google_mirror_disabled(monkeypatch):
    monkeypatch.delenv("WARDEN_GOOGLE_BRAIN_ENABLED", raising=False)
    fn = _get_tool("brain_google_mirror")
    result = json.loads(fn(dry_run=True))
    assert result["ok"] is False


def test_brain_mcp_no_secrets_in_output(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_VAULT_PATH", str(tmp_path))
    fn = _get_tool("brain_status")
    output = fn()
    assert "access_token" not in output
    assert "client_secret" not in output
    assert "refresh_token" not in output
