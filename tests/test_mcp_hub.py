"""Tests for the MCP Hub proxy (src/warden/mcp_hub.py).

Never depend on the real McTable gateway process — the client boundary
functions (_discover_hub_tools / _call_upstream_tool) are monkeypatched
directly, which is the same boundary that wraps ClientSession/
streamablehttp_client, so no real network/subprocess is involved.
"""
import pytest
from mcp import types
from mcp.server.fastmcp import FastMCP

import src.warden.mcp_hub as hub


@pytest.fixture(autouse=True)
def _isolate_optional_upstreams(monkeypatch):
    """Existing hub tests must never contact optional live services."""
    monkeypatch.setenv("WARDEN_CONTEXT7_ENABLED", "0")
    monkeypatch.delenv("WARDEN_MCP_EXTRA_UPSTREAMS_JSON", raising=False)
    monkeypatch.delenv("WARDEN_MCP_HUB_POLICY", raising=False)
    monkeypatch.delenv("WARDEN_MCP_HUB_ALLOW_TOOLS", raising=False)
    hub._tool_routes.clear()
    hub.set_call_guard(None)


def _fresh_mcp() -> FastMCP:
    return FastMCP("test")


NESTED_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "URL to scrape"},
        "format": {"type": "string", "enum": ["markdown", "html"], "default": "markdown"},
        "options": {
            "type": "object",
            "properties": {
                "timeout_ms": {"type": "integer"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "required": ["url"],
}


def _fake_upstream_tool(name="firecrawl_scrape", schema=None) -> types.Tool:
    return types.Tool(
        name=name,
        description="Scrape a URL to markdown",
        inputSchema=schema if schema is not None else NESTED_SCHEMA,
    )


# ---------------------------------------------------------------------------
# Schema fidelity
# ---------------------------------------------------------------------------

def test_schema_fidelity_exact_match():
    mcp = _fresh_mcp()
    upstream = _fake_upstream_tool()
    hub._register_proxied_tool(mcp, upstream)

    tool = mcp._tool_manager._tools["firecrawl_scrape"]
    assert tool.parameters == NESTED_SCHEMA
    assert tool.name == "firecrawl_scrape"
    assert tool.description == "Scrape a URL to markdown"
    assert tool.is_async is True


# ---------------------------------------------------------------------------
# Result fidelity
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_result_fidelity_text(monkeypatch):
    mcp = _fresh_mcp()
    hub._register_proxied_tool(mcp, _fake_upstream_tool())

    expected = types.CallToolResult(
        content=[types.TextContent(type="text", text="hello world")],
        isError=False,
    )

    async def fake_call(name, arguments):
        assert name == "firecrawl_scrape"
        return expected

    monkeypatch.setattr(hub, "_call_upstream_tool", fake_call)

    result = await mcp._tool_manager.call_tool("firecrawl_scrape", {"url": "https://x.com"}, convert_result=True)
    assert result is expected
    assert result.content[0].text == "hello world"


@pytest.mark.anyio
async def test_result_fidelity_multiple_content_blocks(monkeypatch):
    mcp = _fresh_mcp()
    hub._register_proxied_tool(mcp, _fake_upstream_tool())

    expected = types.CallToolResult(
        content=[
            types.TextContent(type="text", text="first block"),
            types.TextContent(type="text", text="second block"),
        ],
        isError=False,
    )

    async def fake_call(name, arguments):
        return expected

    monkeypatch.setattr(hub, "_call_upstream_tool", fake_call)

    result = await mcp._tool_manager.call_tool("firecrawl_scrape", {"url": "https://x.com"}, convert_result=True)
    assert len(result.content) == 2
    assert result.content[0].text == "first block"
    assert result.content[1].text == "second block"


@pytest.mark.anyio
async def test_result_fidelity_structured_content(monkeypatch):
    mcp = _fresh_mcp()
    hub._register_proxied_tool(mcp, _fake_upstream_tool())

    expected = types.CallToolResult(
        content=[types.TextContent(type="text", text="{}")],
        structuredContent={"title": "Example", "word_count": 42},
        isError=False,
    )

    async def fake_call(name, arguments):
        return expected

    monkeypatch.setattr(hub, "_call_upstream_tool", fake_call)

    result = await mcp._tool_manager.call_tool("firecrawl_scrape", {"url": "https://x.com"}, convert_result=True)
    assert result.structuredContent == {"title": "Example", "word_count": 42}


@pytest.mark.anyio
async def test_result_fidelity_is_error(monkeypatch):
    mcp = _fresh_mcp()
    hub._register_proxied_tool(mcp, _fake_upstream_tool())

    expected = types.CallToolResult(
        content=[types.TextContent(type="text", text="upstream failed: rate limited")],
        isError=True,
    )

    async def fake_call(name, arguments):
        return expected

    monkeypatch.setattr(hub, "_call_upstream_tool", fake_call)

    result = await mcp._tool_manager.call_tool("firecrawl_scrape", {"url": "https://x.com"}, convert_result=True)
    assert result.isError is True


@pytest.mark.anyio
async def test_result_fidelity_image_content(monkeypatch):
    mcp = _fresh_mcp()
    hub._register_proxied_tool(mcp, _fake_upstream_tool(name="playwright_screenshot"))

    expected = types.CallToolResult(
        content=[types.ImageContent(type="image", data="base64data==", mimeType="image/png")],
        isError=False,
    )

    async def fake_call(name, arguments):
        return expected

    monkeypatch.setattr(hub, "_call_upstream_tool", fake_call)

    result = await mcp._tool_manager.call_tool("playwright_screenshot", {"url": "https://x.com"}, convert_result=True)
    assert result.content[0].type == "image"
    assert result.content[0].mimeType == "image/png"


@pytest.mark.anyio
async def test_omitted_optional_args_not_forwarded(monkeypatch):
    mcp = _fresh_mcp()
    hub._register_proxied_tool(mcp, _fake_upstream_tool())

    seen = {}

    async def fake_call(name, arguments):
        seen.update(arguments)
        return types.CallToolResult(content=[], isError=False)

    monkeypatch.setattr(hub, "_call_upstream_tool", fake_call)

    await mcp._tool_manager.call_tool("firecrawl_scrape", {"url": "https://x.com"}, convert_result=True)
    assert seen == {"url": "https://x.com"}


# ---------------------------------------------------------------------------
# bootstrap_hub: error isolation, collisions, happy path
# ---------------------------------------------------------------------------

def test_bootstrap_hub_gateway_unreachable(monkeypatch):
    mcp = _fresh_mcp()

    @mcp.tool()
    def native_tool() -> str:
        return "ok"

    async def fake_discover():
        raise ConnectionError("connection refused")

    monkeypatch.setattr(hub, "_discover_hub_tools", fake_discover)

    status = hub.bootstrap_hub(mcp)

    assert status.reachable_at_boot is False
    assert status.hub_tool_count == 0
    assert status.last_error is not None
    # native tool untouched
    assert "native_tool" in mcp._tool_manager._tools


def test_bootstrap_hub_happy_path(monkeypatch):
    mcp = _fresh_mcp()

    fake_tools = [
        _fake_upstream_tool(name="firecrawl_scrape"),
        _fake_upstream_tool(name="github_search_code", schema={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}),
    ]

    async def fake_discover():
        return fake_tools

    monkeypatch.setattr(hub, "_discover_hub_tools", fake_discover)

    status = hub.bootstrap_hub(mcp)

    assert status.reachable_at_boot is True
    assert status.hub_tool_count == 2
    assert set(status.hub_tool_names) == {"firecrawl_scrape", "github_search_code"}
    assert "firecrawl_scrape" in mcp._tool_manager._tools
    assert "github_search_code" in mcp._tool_manager._tools


def test_bootstrap_hub_skips_name_collision(monkeypatch):
    mcp = _fresh_mcp()

    @mcp.tool()
    def firecrawl_scrape() -> str:
        """Warden's own native tool, coincidentally same name."""
        return "native"

    async def fake_discover():
        return [_fake_upstream_tool(name="firecrawl_scrape")]

    monkeypatch.setattr(hub, "_discover_hub_tools", fake_discover)

    status = hub.bootstrap_hub(mcp)

    assert status.hub_tool_count == 0
    assert "firecrawl_scrape" in status.skipped_collisions
    # native tool's schema (derived from the real function signature) must
    # not have been overwritten by the hub's Tool object
    native = mcp._tool_manager._tools["firecrawl_scrape"]
    assert native.parameters != NESTED_SCHEMA


# ---------------------------------------------------------------------------
# Multiple upstreams: Context7 + operator-configured services
# ---------------------------------------------------------------------------

def test_context7_configuration_uses_server_key_without_exposing_it(monkeypatch):
    monkeypatch.setenv("WARDEN_CONTEXT7_ENABLED", "1")
    monkeypatch.setenv("CONTEXT7_API_KEY", "private-context7-key")

    upstreams = hub._configured_extra_upstreams()

    assert len(upstreams) == 1
    assert upstreams[0].name == "context7"
    assert upstreams[0].prefix == "context7_"
    assert upstreams[0].headers == {"CONTEXT7_API_KEY": "private-context7-key"}


def test_generic_upstream_resolves_header_values_from_env(monkeypatch):
    monkeypatch.setenv("DOCS_BEARER", "Bearer secret-value")
    monkeypatch.setenv("WARDEN_MCP_EXTRA_UPSTREAMS_JSON", """[
        {"name":"Docs API","url":"https://docs.example/mcp","prefix":"docs-api",
         "header_env":{"Authorization":"DOCS_BEARER"},
         "allow_tools":["search-docs"]}
    ]""")

    upstreams = hub._configured_extra_upstreams()

    assert len(upstreams) == 1
    assert upstreams[0].name == "Docs API"
    assert upstreams[0].prefix == "docs_api_"
    assert upstreams[0].headers == {"Authorization": "Bearer secret-value"}
    assert upstreams[0].allowed_tools == frozenset({"search-docs"})


def test_bootstrap_registers_context7_with_stable_prefixed_names(monkeypatch):
    mcp = _fresh_mcp()
    monkeypatch.setenv("WARDEN_CONTEXT7_ENABLED", "1")

    async def fake_primary_discovery():
        return [_fake_upstream_tool(name="github_search_code")]

    async def fake_extra_discovery(upstream):
        assert upstream.name == "context7"
        return [
            _fake_upstream_tool(name="resolve-library-id"),
            _fake_upstream_tool(name="query-docs"),
        ]

    monkeypatch.setattr(hub, "_discover_hub_tools", fake_primary_discovery)
    monkeypatch.setattr(hub, "_discover_tools_from", fake_extra_discovery)

    status = hub.bootstrap_hub(mcp)

    assert status.reachable_at_boot is True
    assert status.hub_tool_count == 3
    assert status.hub_tool_names == [
        "github_search_code",
        "context7_resolve_library_id",
        "context7_query_docs",
    ]
    assert status.upstreams == [
        {"name": "mctable", "reachable": True, "tool_count": 1,
         "discovered_tool_count": 1, "blocked_by_policy": 0,
         "tool_names": ["github_search_code"], "error": None},
        {"name": "context7", "reachable": True, "tool_count": 2,
         "discovered_tool_count": 2, "blocked_by_policy": 0,
         "tool_names": ["context7_resolve_library_id", "context7_query_docs"],
         "error": None},
    ]
    assert hub._tool_routes["context7_query_docs"][1] == "query-docs"
    assert "private" not in repr(status)


def test_optional_upstream_survives_primary_gateway_outage(monkeypatch):
    mcp = _fresh_mcp()
    monkeypatch.setenv("WARDEN_CONTEXT7_ENABLED", "1")

    async def failed_primary_discovery():
        raise ConnectionError("gateway offline")

    async def healthy_context7_discovery(upstream):
        return [_fake_upstream_tool(name="query-docs")]

    monkeypatch.setattr(hub, "_discover_hub_tools", failed_primary_discovery)
    monkeypatch.setattr(hub, "_discover_tools_from", healthy_context7_discovery)

    status = hub.bootstrap_hub(mcp)

    assert status.reachable_at_boot is False
    assert status.hub_tool_names == ["context7_query_docs"]
    assert "context7_query_docs" in mcp._tool_manager._tools
    assert status.upstreams[0]["name"] == "mctable"
    assert status.upstreams[0]["reachable"] is False
    assert status.upstreams[1] == {
        "name": "context7", "reachable": True, "tool_count": 1,
        "discovered_tool_count": 1, "blocked_by_policy": 0,
        "tool_names": ["context7_query_docs"], "error": None,
    }


# ---------------------------------------------------------------------------
# Public service policy + Warden-first call guard
# ---------------------------------------------------------------------------

def test_default_policy_exposes_reads_and_omits_mutations(monkeypatch):
    mcp = _fresh_mcp()

    async def fake_discover():
        return [
            _fake_upstream_tool(name="github_search_code"),
            _fake_upstream_tool(name="github_push_files"),
            _fake_upstream_tool(name="desktopcmd_start_process"),
            _fake_upstream_tool(name="fs_read_file"),
        ]

    monkeypatch.setattr(hub, "_discover_hub_tools", fake_discover)
    status = hub.bootstrap_hub(mcp)

    assert status.hub_tool_names == ["github_search_code"]
    assert set(status.blocked_by_policy) == {
        "github_push_files", "desktopcmd_start_process", "fs_read_file",
    }
    assert "github_push_files" not in mcp._tool_manager._tools


def test_operator_can_explicitly_allow_one_upstream_tool(monkeypatch):
    mcp = _fresh_mcp()
    monkeypatch.setenv("WARDEN_MCP_HUB_ALLOW_TOOLS", "github_create_issue")

    async def fake_discover():
        return [
            _fake_upstream_tool(name="github_create_issue"),
            _fake_upstream_tool(name="github_push_files"),
        ]

    monkeypatch.setattr(hub, "_discover_hub_tools", fake_discover)
    status = hub.bootstrap_hub(mcp)

    assert status.hub_tool_names == ["github_create_issue"]
    assert status.blocked_by_policy == ["github_push_files"]


@pytest.mark.anyio
async def test_call_guard_blocks_before_upstream_invocation(monkeypatch):
    mcp = _fresh_mcp()
    hub._register_proxied_tool(mcp, _fake_upstream_tool(name="github_search_code"))
    called = False

    async def fake_call(name, arguments):
        nonlocal called
        called = True
        return types.CallToolResult(content=[], isError=False)

    monkeypatch.setattr(hub, "_call_upstream_tool", fake_call)
    hub.set_call_guard(lambda name: "Call warden_bootstrap first")

    result = await mcp._tool_manager.call_tool(
        "github_search_code", {"url": "https://example.com"}, convert_result=True,
    )

    assert result.isError is True
    assert result.content[0].text == "Call warden_bootstrap first"
    assert called is False
