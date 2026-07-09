"""Tests for the Warden Brain read-only server-status MCP tools."""
import json
import subprocess

import pytest


def _get_tool(name):
    import src.warden.brain_mcp_server as mcp_mod
    for tool_name, fn in mcp_mod.mcp._tool_manager._tools.items():
        if tool_name == name:
            return fn.fn
    raise KeyError(f"Tool not found: {name}")


def test_server_status_tools_registered():
    import src.warden.brain_mcp_server as mod
    tool_names = list(mod.mcp._tool_manager._tools.keys())
    assert "warden_server_status" in tool_names
    assert "warden_service_health" in tool_names
    assert "warden_repo_catalog" in tool_names
    assert "warden_listening_ports" in tool_names


def test_warden_server_status_returns_ok():
    fn = _get_tool("warden_server_status")
    result = json.loads(fn())
    assert result["ok"] is True
    assert "disk" in result["data"]
    assert "memory" in result["data"]
    assert "services" in result["data"]


def test_warden_server_status_no_secrets_in_output():
    fn = _get_tool("warden_server_status")
    output = fn()
    assert "access_token" not in output
    assert "client_secret" not in output
    assert "refresh_token" not in output


def test_warden_service_health_default_allowlist():
    fn = _get_tool("warden_service_health")
    result = json.loads(fn())
    assert result["ok"] is True
    names = [s["service"] for s in result["data"]["services"]]
    assert names == result["data"]["allowlist"]


def test_warden_service_health_filters_to_requested_subset():
    fn = _get_tool("warden_service_health")
    result = json.loads(fn(services="mcharness-cockpit"))
    assert result["ok"] is True
    names = [s["service"] for s in result["data"]["services"]]
    assert names == ["mcharness-cockpit"]


def test_warden_service_health_ignores_unknown_names():
    fn = _get_tool("warden_service_health")
    result = json.loads(fn(services="rm -rf /, some-other-service"))
    assert result["ok"] is True
    assert result["data"]["services"] == []


def test_warden_repo_catalog_finds_repos(tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".git").mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=False)

    fn = _get_tool("warden_repo_catalog")
    result = json.loads(fn(root=str(tmp_path)))
    assert result["ok"] is True
    paths = [r["path"] for r in result["data"]["repos"]]
    assert str(repo) in paths


def test_warden_repo_catalog_rejects_missing_root():
    fn = _get_tool("warden_repo_catalog")
    result = json.loads(fn(root="/this/path/does/not/exist"))
    assert result["ok"] is False


def test_warden_listening_ports_returns_ok_or_graceful_error():
    fn = _get_tool("warden_listening_ports")
    result = json.loads(fn())
    # ss may be unavailable in some CI sandboxes; either a clean ok result
    # or a graceful, non-crashing error is acceptable.
    assert "ok" in result
    if result["ok"]:
        assert "ports" in result["data"]
