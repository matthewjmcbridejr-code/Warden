"""Tests for mail MCP tools and Marius Agent mail tool integration."""
import json
import pytest
from fastapi.testclient import TestClient
from src.warden.app import app


# ─── Marius Agent mail tool schemas ───────────────────────────────────────────

def test_agent_has_mail_tool_schemas():
    """Agent TOOL_SCHEMAS includes mail_accounts, mail_search, mail_read_message."""
    from src.warden.agent import TOOL_SCHEMAS
    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    assert "mail_accounts" in names
    assert "mail_search" in names
    assert "mail_read_message" in names


def test_mail_search_schema_requires_account_id_and_query():
    from src.warden.agent import TOOL_SCHEMAS
    schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "mail_search")
    required = schema["function"]["parameters"].get("required", [])
    assert "account_id" in required
    assert "query" in required


def test_mail_read_message_schema_requires_both_params():
    from src.warden.agent import TOOL_SCHEMAS
    schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "mail_read_message")
    required = schema["function"]["parameters"].get("required", [])
    assert "account_id" in required
    assert "message_id" in required


# ─── Mail tools in TOOL_FUNCTIONS ─────────────────────────────────────────────

def test_mail_accounts_tool_returns_dict():
    """tool_mail_accounts returns a dict even when API is unreachable."""
    from src.warden.agent import tool_mail_accounts
    result = tool_mail_accounts()
    assert isinstance(result, dict)
    # Either connected=False (API unreachable) or has accounts list
    assert "connected" in result or "error" in result


def test_mail_search_tool_requires_account_id():
    """tool_mail_search without account_id returns blocked error."""
    from src.warden.agent import tool_mail_search
    result = tool_mail_search("", "test query")
    assert result.get("blocked") is True or "error" in result


def test_mail_read_message_tool_requires_both():
    """tool_mail_read_message without required params returns error."""
    from src.warden.agent import tool_mail_read_message
    result = tool_mail_read_message("", "")
    assert "error" in result


# ─── MCP brain server mail tools ──────────────────────────────────────────────

def test_mcp_mail_send_draft_blocked_by_default(monkeypatch):
    """warden_mail_send_draft returns blocked=True without WARDEN_MAIL_ALLOW_SEND."""
    monkeypatch.delenv("WARDEN_MAIL_ALLOW_SEND", raising=False)
    from src.warden.brain_mcp_server import warden_mail_send_draft
    result = json.loads(warden_mail_send_draft("acc", "a@b.com", "Test", "Body"))
    # Result is wrapped in {ok, data} envelope
    data = result.get("data", result)
    assert data.get("blocked") is True


def test_mcp_mail_search_returns_error_without_account_id():
    """warden_mail_search with empty account_id returns error."""
    from src.warden.brain_mcp_server import warden_mail_search
    result = json.loads(warden_mail_search("", "test"))
    assert "error" in result or result.get("ok") is False


# ─── Mail trace step in Marius Agent ──────────────────────────────────────────

def test_mail_tool_appears_in_trace(monkeypatch):
    """When mail_search is called, trace includes tool_action step."""
    import src.warden.agent as agent_mod
    from src.warden.agent import AgentResponse, _build_trace

    tools_used = [
        {"tool": "mail_accounts", "args": {}, "result_preview": '{"connected": false}'},
        {"tool": "mail_search", "args": {"account_id": "acc-1", "query": "invoice"},
         "result_preview": '{"count": 1, "messages": []}'},
    ]
    trace = _build_trace(tools_used, ["mail"], fallback=False)
    assert trace is not None
    step_labels = [s["label"] for s in trace["steps"]]
    assert "mail_accounts" in step_labels
    assert "mail_search" in step_labels


def test_mail_trace_no_token_in_steps():
    """Trace steps from mail tools never contain token/password values."""
    from src.warden.agent import _build_trace
    tools_used = [
        {"tool": "mail_search", "args": {"account_id": "acc-1", "query": "test"},
         "result_preview": '{"messages": [], "count": 0}'},
    ]
    # Ensure no suspicious content sneaks into trace from result_preview
    trace = _build_trace(tools_used, ["mail"], fallback=False)
    trace_str = json.dumps(trace)
    assert "access_token" not in trace_str
    assert "app_password" not in trace_str
    assert "refresh_token" not in trace_str
