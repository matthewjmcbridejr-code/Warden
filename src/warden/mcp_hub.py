"""MCP Hub — exposes Warden's configured upstream MCP services.

Warden acts as an MCP *client* to the already-running McTable gateway
(src/mctable/mcp_gateway.py in the marius-mind-code repo, exposed locally at
WARDEN_MCP_HUB_URL) and re-registers each discovered tool on Warden's own
FastMCP instance. Its default policy exposes only reviewed read-only McTable,
GitHub, and research tools; process execution, filesystem access, browser
control, repository mutation, and destructive memory tools fail closed unless
the operator explicitly allows exact tool names.
Context7 is mounted as a second built-in upstream, and additional MCP services
can be declared through ``WARDEN_MCP_EXTRA_UPSTREAMS_JSON``. Remote agents
still authenticate only once to Warden; upstream credentials stay server-side.

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
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

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
CONTEXT7_URL = os.getenv("WARDEN_CONTEXT7_MCP_URL", "https://mcp.context7.com/mcp")
DISCOVERY_TIMEOUT_SECONDS = 10.0
CALL_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class HubUpstream:
    """One upstream whose tools are surfaced through Warden.

    ``headers`` may contain resolved secrets, so status output deliberately
    exposes only the upstream name, reachability, and tool count.
    """

    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    prefix: str = ""
    allowed_tools: frozenset[str] = field(default_factory=frozenset)


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
    blocked_by_policy: list[str] = field(default_factory=list)
    upstreams: list[dict[str, Any]] = field(default_factory=list)


_hub_status = HubStatus()
_tool_routes: dict[str, tuple[HubUpstream, str]] = {}
_call_guard: Callable[[str], str | None] | None = None


_MCTABLE_READ_ONLY_PATTERNS = (
    re.compile(r"^mctable(?:_|\.)(?:get|list|search)"),
    re.compile(r"^github_(?:get|list|search)_"),
)
_FIRECRAWL_READ_TOOLS = frozenset({
    "firecrawl_firecrawl_scrape",
    "firecrawl_firecrawl_map",
    "firecrawl_firecrawl_search",
    "firecrawl_firecrawl_check_crawl_status",
    "firecrawl_firecrawl_research_search_papers",
    "firecrawl_firecrawl_research_inspect_paper",
    "firecrawl_firecrawl_research_related_papers",
    "firecrawl_firecrawl_research_read_paper",
    "firecrawl_firecrawl_research_search_github",
    "firecrawl_firecrawl_developer_search",
    # Legacy gateway names retained for backwards-compatible tests/config.
    "firecrawl_scrape",
})


def hub_status() -> HubStatus:
    """Current hub status, populated once by bootstrap_hub()."""
    return _hub_status


def set_call_guard(guard: Callable[[str], str | None] | None) -> None:
    """Install a per-request preflight guard for proxied service calls."""
    global _call_guard
    _call_guard = guard


def _operator_allowed_tools() -> frozenset[str]:
    return frozenset(
        name.strip()
        for name in os.getenv("WARDEN_MCP_HUB_ALLOW_TOOLS", "").split(",")
        if name.strip()
    )


def _tool_allowed(upstream: HubUpstream, upstream_name: str, public_name: str) -> bool:
    """Fail closed for upstream tools unless they are read-only or explicitly allowed."""
    policy = os.getenv("WARDEN_MCP_HUB_POLICY", "read_only").strip().lower()
    if policy == "all":
        return True
    if policy in {"off", "disabled", "none"}:
        return False

    explicit = _operator_allowed_tools()
    if upstream_name in explicit or public_name in explicit:
        return True
    if upstream_name in upstream.allowed_tools or public_name in upstream.allowed_tools:
        return True
    if upstream.name != "mctable":
        return False
    return (
        upstream_name in _FIRECRAWL_READ_TOOLS
        or any(pattern.match(upstream_name) for pattern in _MCTABLE_READ_ONLY_PATTERNS)
    )


def _auth_headers() -> dict[str, str]:
    if GATEWAY_TOKEN:
        return {"Authorization": f"Bearer {GATEWAY_TOKEN}"}
    return {}


def _primary_upstream() -> HubUpstream:
    return HubUpstream(name="mctable", url=GATEWAY_URL, headers=_auth_headers())


def _normalise_prefix(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.strip().lower())
    cleaned = cleaned.strip("_")
    return f"{cleaned}_" if cleaned else ""


def _configured_extra_upstreams() -> list[HubUpstream]:
    """Return Context7 plus optional operator-configured MCP services.

    Context7 supports anonymous calls, so it is enabled unless explicitly
    disabled with ``WARDEN_CONTEXT7_ENABLED=0``. If ``CONTEXT7_API_KEY`` is
    available, Warden supplies it without exposing it to connected agents.

    Extra services use a JSON list such as::

        [{"name":"docs","url":"https://example/mcp",
          "prefix":"docs","header_env":{"Authorization":"DOCS_AUTH"}}]

    Values in ``header_env`` are environment-variable names, never secrets.
    """

    upstreams: list[HubUpstream] = []
    if os.getenv("WARDEN_CONTEXT7_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}:
        context7_key = os.getenv("CONTEXT7_API_KEY", "").strip()
        headers = {"CONTEXT7_API_KEY": context7_key} if context7_key else {}
        upstreams.append(HubUpstream(
            name="context7",
            url=CONTEXT7_URL,
            headers=headers,
            prefix="context7_",
            allowed_tools=frozenset({"resolve-library-id", "query-docs"}),
        ))

    raw = os.getenv("WARDEN_MCP_EXTRA_UPSTREAMS_JSON", "").strip()
    if not raw:
        return upstreams
    try:
        records = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("mcp_hub: invalid WARDEN_MCP_EXTRA_UPSTREAMS_JSON: %s", exc)
        return upstreams
    if not isinstance(records, list):
        log.warning("mcp_hub: WARDEN_MCP_EXTRA_UPSTREAMS_JSON must be a list")
        return upstreams

    for record in records:
        if not isinstance(record, dict):
            continue
        name = str(record.get("name", "")).strip()
        url = str(record.get("url", "")).strip()
        if not name or not url.startswith(("http://", "https://")):
            log.warning("mcp_hub: skipping invalid extra upstream %r", name or record)
            continue
        headers: dict[str, str] = {}
        header_env = record.get("header_env", {})
        if isinstance(header_env, dict):
            for header_name, env_name in header_env.items():
                value = os.getenv(str(env_name), "").strip()
                if value:
                    headers[str(header_name)] = value
        allowed_tools = record.get("allow_tools", [])
        if not isinstance(allowed_tools, list):
            allowed_tools = []
        upstreams.append(HubUpstream(
            name=name,
            url=url,
            headers=headers,
            prefix=_normalise_prefix(str(record.get("prefix", name))),
            allowed_tools=frozenset(str(item).strip() for item in allowed_tools if str(item).strip()),
        ))
    return upstreams


async def _discover_tools_from(upstream: HubUpstream) -> list[types.Tool]:
    async with streamablehttp_client(
        upstream.url,
        headers=upstream.headers,
        timeout=DISCOVERY_TIMEOUT_SECONDS,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


async def _discover_hub_tools() -> list[types.Tool]:
    """Connect to the gateway, list its tools, and disconnect.

    Never keeps the session alive past this call — the bootstrap event loop
    (asyncio.run in bootstrap_hub) is separate from the server's real serving
    loop (uvicorn / mcp.run_stdio_async), and asyncio streams don't transfer
    across loops safely. Each proxied tool call later opens its own
    short-lived session instead of relying on a persisted one.
    """
    return await _discover_tools_from(_primary_upstream())


async def _call_upstream_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """Open a fresh short-lived session, call one tool, close. See module docstring."""
    upstream, upstream_name = _tool_routes.get(name, (_primary_upstream(), name))
    async with streamablehttp_client(
        upstream.url,
        headers=upstream.headers,
        timeout=CALL_TIMEOUT_SECONDS,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(upstream_name, arguments)


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
        f"{upstream_tool.name.replace('-', '_')}HubArguments",
        __base__=ArgModelBase,
        **field_defs,
    )


def _register_proxied_tool(
    mcp: FastMCP,
    upstream_tool: types.Tool,
    *,
    upstream: HubUpstream | None = None,
    public_name: str | None = None,
) -> None:
    """Register one gateway tool on Warden's FastMCP instance, preserving its
    exact schema and preserving full CallToolResult fidelity on call."""

    route = upstream or _primary_upstream()
    exposed_name = public_name or upstream_tool.name

    async def _proxy_fn(**kwargs: Any) -> types.CallToolResult:
        if _call_guard is not None:
            try:
                guard_error = _call_guard(exposed_name)
            except Exception:
                log.exception("mcp_hub: call guard failed for %s", exposed_name)
                guard_error = "Warden's service preflight failed closed; the upstream was not called."
            if guard_error:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=guard_error)],
                    isError=True,
                )
        # Drop args the caller didn't actually supply (our permissive arg
        # model defaults every property to None) so we don't send spurious
        # nulls upstream for fields the caller omitted entirely.
        call_args = {k: v for k, v in kwargs.items() if v is not None}
        return await _call_upstream_tool(exposed_name, call_args)

    _proxy_fn.__name__ = f"hub_proxy_{exposed_name.replace('-', '_')}"
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
        name=exposed_name,
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
    _tool_routes[exposed_name] = (route, upstream_tool.name)


def bootstrap_hub(mcp: FastMCP) -> HubStatus:
    """Discover and register configured upstream tools on ``mcp``.

    Every upstream is isolated: a gateway or third-party outage must never
    prevent Warden's native tools or another healthy upstream from serving.
    """
    global _hub_status

    native_names = set(name for name in mcp._tool_manager._tools.keys() if name not in _tool_routes)
    _tool_routes.clear()
    status = HubStatus(native_tool_count=len(native_names))
    registered: list[str] = []
    skipped: list[str] = []
    blocked: list[str] = []

    try:
        upstream_tools = asyncio.run(_discover_hub_tools())
    except Exception as exc:
        log.warning("mcp_hub: gateway unreachable at %s: %s", GATEWAY_URL, exc)
        status.last_error = str(exc)
        upstream_tools = []
        status.upstreams.append({
            "name": "mctable", "reachable": False, "tool_count": 0,
            "discovered_tool_count": 0, "blocked_by_policy": 0,
            "tool_names": [], "error": str(exc),
        })
    else:
        status.reachable_at_boot = True
        primary_count = 0
        primary_blocked = 0
        for upstream_tool in upstream_tools:
            if upstream_tool.name in native_names:
                log.warning("mcp_hub: skipping %r — collides with a native Warden tool", upstream_tool.name)
                skipped.append(upstream_tool.name)
                continue
            if not _tool_allowed(_primary_upstream(), upstream_tool.name, upstream_tool.name):
                blocked.append(upstream_tool.name)
                primary_blocked += 1
                continue
            try:
                _register_proxied_tool(mcp, upstream_tool)
                registered.append(upstream_tool.name)
                primary_count += 1
            except Exception as exc:
                log.warning("mcp_hub: failed to register %r: %s", upstream_tool.name, exc)
                skipped.append(upstream_tool.name)
        status.upstreams.append({
            "name": "mctable", "reachable": True, "tool_count": primary_count,
            "discovered_tool_count": len(upstream_tools), "blocked_by_policy": primary_blocked,
            "tool_names": registered[:primary_count],
            "error": None,
        })

    occupied_names = native_names | set(registered)
    for upstream in _configured_extra_upstreams():
        try:
            extra_tools = asyncio.run(_discover_tools_from(upstream))
        except Exception as exc:
            log.warning("mcp_hub: upstream %s unreachable at %s: %s", upstream.name, upstream.url, exc)
            status.upstreams.append({
                "name": upstream.name, "reachable": False, "tool_count": 0,
                "discovered_tool_count": 0, "blocked_by_policy": 0,
                "tool_names": [], "error": str(exc),
            })
            continue

        upstream_count = 0
        upstream_blocked = 0
        upstream_registered: list[str] = []
        for upstream_tool in extra_tools:
            public_name = f"{upstream.prefix}{upstream_tool.name.replace('-', '_')}"
            if public_name in occupied_names:
                skipped.append(public_name)
                continue
            if not _tool_allowed(upstream, upstream_tool.name, public_name):
                blocked.append(public_name)
                upstream_blocked += 1
                continue
            try:
                _register_proxied_tool(
                    mcp,
                    upstream_tool,
                    upstream=upstream,
                    public_name=public_name,
                )
                registered.append(public_name)
                upstream_registered.append(public_name)
                occupied_names.add(public_name)
                upstream_count += 1
            except Exception as exc:
                log.warning("mcp_hub: failed to register %s from %s: %s", public_name, upstream.name, exc)
                skipped.append(public_name)
        status.upstreams.append({
            "name": upstream.name,
            "reachable": True,
            "tool_count": upstream_count,
            "discovered_tool_count": len(extra_tools),
            "blocked_by_policy": upstream_blocked,
            "tool_names": upstream_registered,
            "error": None,
        })

    status.last_discovery_at = datetime.now(timezone.utc).isoformat()
    status.hub_tool_count = len(registered)
    status.hub_tool_names = registered
    status.skipped_collisions = skipped
    status.blocked_by_policy = blocked
    log.warning(
        "mcp_hub: registered %d tools across %d upstreams (%d skipped)",
        len(registered), len(status.upstreams), len(skipped),
    )
    _hub_status = status
    return status
