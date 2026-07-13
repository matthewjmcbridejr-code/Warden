"""MCP Hub — proxies the McTable MCP gateway's tools into Warden.

Warden acts as an MCP *client* to the already-running McTable gateway
(src/mctable/mcp_gateway.py in the marius-mind-code repo, exposed locally at
WARDEN_MCP_HUB_URL) and re-registers each discovered tool on Warden's own
FastMCP instance, so any agent connected to Warden's /mcp also gets the
gateway's tools (github_, playwright_, fs_, sqlite_, git_, desktopcmd_,
memory_, firecrawl_, supadata_, brave_, stripe_, context7, plus McTable's
own unnamespaced control-plane tools) with no separate connection required.

Registration deliberately bypasses the normal `@mcp.tool()` decorator /
`ToolManager.add_tool()` path. Both derive the advertised JSON schema from
the Python callable's signature (mcp.server.fastmcp.tools.base.Tool.from_function
-> utilities.func_metadata.func_metadata -> arg_model.model_json_schema()),
which would flatten every proxied tool's real inputSchema into a meaningless
generic schema. Instead this module constructs `Tool`/`FuncMetadata` objects
directly (mcp==1.28.1 internals, see _register_proxied_tool) so the exact
upstream inputSchema is preserved verbatim, and proxy functions return the
upstream `CallToolResult` unmodified so FuncMetadata.convert_result() passes
it straight through (confirmed: it special-cases CallToolResult results when
output_schema is None). If a future `mcp` SDK upgrade changes these classes,
this is the one place to fix.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import create_model

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, FuncMetadata

log = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("WARDEN_MCP_HUB_URL", "http://127.0.0.1:8082/mcp")
GATEWAY_TOKEN = os.getenv("WARDEN_MCP_HUB_TOKEN", "")
DISCOVERY_TIMEOUT_SECONDS = 10.0
CALL_TIMEOUT_SECONDS = 60.0


@dataclass
class HubStatus:
    enabled: bool = True
    reachable_at_boot: bool = False
    last_discovery_at: str | None = None
    last_error: str | None = None
    hub_tool_count: int = 0
    native_tool_count: int = 0
    hub_tool_names: list[str] = field(default_factory=list)
    skipped_collisions: list[str] = field(default_factory=list)


_hub_status = HubStatus()


def hub_status() -> HubStatus:
    """Current hub status, populated once by bootstrap_hub()."""
    return _hub_status


def _auth_headers() -> dict[str, str]:
    if GATEWAY_TOKEN:
        return {"Authorization": f"Bearer {GATEWAY_TOKEN}"}
    return {}


async def _discover_hub_tools() -> list[types.Tool]:
    """Connect to the gateway, list its tools, and disconnect.

    Never keeps the session alive past this call — the bootstrap event loop
    (asyncio.run in bootstrap_hub) is separate from the server's real serving
    loop (uvicorn / mcp.run_stdio_async), and asyncio streams don't transfer
    across loops safely. Each proxied tool call later opens its own
    short-lived session instead of relying on a persisted one.
    """
    async with streamablehttp_client(
        GATEWAY_URL,
        headers=_auth_headers(),
        timeout=DISCOVERY_TIMEOUT_SECONDS,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


async def _call_upstream_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """Open a fresh short-lived session, call one tool, close. See module docstring."""
    async with streamablehttp_client(
        GATEWAY_URL,
        headers=_auth_headers(),
        timeout=CALL_TIMEOUT_SECONDS,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, arguments)


def _build_permissive_arg_model(upstream_tool: types.Tool) -> type[ArgModelBase]:
    """Build an internal arg model that forwards exactly the upstream's argument
    keys, all optional (default None).

    This model's own generated schema is never shown to clients — the
    advertised schema is `upstream_tool.inputSchema` set directly on the
    constructed Tool.parameters below. Real validation/enforcement is
    whatever the upstream gateway itself does; duplicating its required/enum/
    type constraints here would only risk rejecting something the real
    schema would have accepted. extra="allow" alone is not enough here:
    ArgModelBase.model_dump_one_level() only dumps *declared* model_fields,
    so every upstream property must be an explicit field.
    """
    properties = (upstream_tool.inputSchema or {}).get("properties", {})
    field_defs: dict[str, Any] = {name: (Any, None) for name in properties}
    return create_model(
        f"{upstream_tool.name}HubArguments",
        __base__=ArgModelBase,
        **field_defs,
    )


def _register_proxied_tool(mcp: FastMCP, upstream_tool: types.Tool) -> None:
    """Register one gateway tool on Warden's FastMCP instance, preserving its
    exact schema and preserving full CallToolResult fidelity on call."""

    async def _proxy_fn(**kwargs: Any) -> types.CallToolResult:
        # Drop args the caller didn't actually supply (our permissive arg
        # model defaults every property to None) so we don't send spurious
        # nulls upstream for fields the caller omitted entirely.
        call_args = {k: v for k, v in kwargs.items() if v is not None}
        return await _call_upstream_tool(upstream_tool.name, call_args)

    _proxy_fn.__name__ = f"hub_proxy_{upstream_tool.name}"
    _proxy_fn.__doc__ = upstream_tool.description or ""

    arg_model = _build_permissive_arg_model(upstream_tool)
    fn_metadata = FuncMetadata(
        arg_model=arg_model,
        output_schema=None,
        output_model=None,
        wrap_output=False,
    )

    tool = Tool(
        fn=_proxy_fn,
        name=upstream_tool.name,
        title=None,
        description=upstream_tool.description or "",
        parameters=upstream_tool.inputSchema,
        fn_metadata=fn_metadata,
        is_async=True,
        context_kwarg=None,
        annotations=upstream_tool.annotations,
        icons=upstream_tool.icons,
        meta=upstream_tool.meta,
    )
    # Direct private-attribute registration — see module docstring. FastMCP's
    # public `add_tool()`/`.tool()` always derive `parameters` from the
    # wrapper function's signature, which would lose the upstream schema.
    mcp._tool_manager._tools[tool.name] = tool


def bootstrap_hub(mcp: FastMCP) -> HubStatus:
    """Discover and register the gateway's tools on `mcp`. Never raises —
    a hub outage must never prevent Warden's own tools from serving."""
    global _hub_status

    native_names = set(mcp._tool_manager._tools.keys())
    status = HubStatus(native_tool_count=len(native_names))

    try:
        upstream_tools = asyncio.run(_discover_hub_tools())
    except Exception as exc:
        log.warning("mcp_hub: gateway unreachable at %s: %s", GATEWAY_URL, exc)
        status.reachable_at_boot = False
        status.last_error = str(exc)
        status.last_discovery_at = datetime.now(timezone.utc).isoformat()
        _hub_status = status
        return status

    status.reachable_at_boot = True
    status.last_discovery_at = datetime.now(timezone.utc).isoformat()

    registered = []
    skipped = []
    for upstream_tool in upstream_tools:
        if upstream_tool.name in native_names:
            log.warning("mcp_hub: skipping %r — collides with a native Warden tool", upstream_tool.name)
            skipped.append(upstream_tool.name)
            continue
        try:
            _register_proxied_tool(mcp, upstream_tool)
            registered.append(upstream_tool.name)
        except Exception as exc:
            log.warning("mcp_hub: failed to register %r: %s", upstream_tool.name, exc)
            skipped.append(upstream_tool.name)

    status.hub_tool_count = len(registered)
    status.hub_tool_names = registered
    status.skipped_collisions = skipped
    log.warning(
        "mcp_hub: registered %d/%d gateway tools (%d skipped)",
        len(registered), len(upstream_tools), len(skipped),
    )
    _hub_status = status
    return status
