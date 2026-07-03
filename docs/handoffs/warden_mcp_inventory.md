# Warden MCP Inventory

**Date:** 2026-06-29  
**Branch:** feat/marius-resident-core  

## Existing MCP Architecture

### Server: `warden-brain` (stdio)

**Entry point:** `scripts/warden-brain-mcp` → `src/warden/brain_mcp_server.py`  
**Transport:** stdio (FastMCP)  
**Config:** `.mcp.json` → `mcpServers.warden-brain`  

### Current Tools (17)

| Tool | Description | Kind |
|---|---|---|
| `warden_health` | Health + version | read_only |
| `warden_me` | Matt's identity/profile | read_only |
| `warden_workstream` | Recent activity across projects | read_only |
| `warden_update_me` | Update profile field | write_gated |
| `warden_who_is_working` | Active agents/sessions | read_only |
| `warden_recall` | Search memories by query | read_only |
| `warden_context_pack` | Structured memory context for a task | read_only |
| `warden_remember` | Save a memory | write_gated |
| `warden_ingest` | Ingest document/text to brain | write_gated |
| `warden_search_docs` | Search project docs | read_only |
| `warden_bootstrap` | Bootstrap session for a task | read_only |
| `warden_board` | View task board | read_only |
| `warden_post_task` | Create a task | write_gated |
| `warden_claim_task` | Claim a task | write_gated |
| `warden_handoff` | Write handoff note | write_gated |
| `warden_agent` | Ask Warden Agent (tool-calling) | read_only |
| `warden_ask_marius` | Ask Marius (LLM gateway) | read_only |
| `warden_memory_context` | Live memory context snapshot | read_only |

### Secondary MCP: `src/warden/mcp.py`
- Different schema (`warden.mcp.v1`), handles task/worker dispatch
- Not exposed in `.mcp.json` currently — internal use

## Gaps for New Architecture

| Tool Needed | Status | Action |
|---|---|---|
| `captain.plan` | Missing | Add to brain_mcp_server |
| `captain.recent_plans` | Missing | Add to brain_mcp_server |
| `captain.dispatch_step` | Missing | Add to brain_mcp_server |
| `runs.get` | Missing | Add to brain_mcp_server |
| `trace.latest` | Pending Marius Trace impl | Add after trace exists |
| `connectors.providers` | Missing | Add placeholder |
| `connectors.accounts` | Missing | Add placeholder |
| `mail.accounts_status` | Missing | Add placeholder |

## What Will Be Reused

- `warden_recall` / `warden_remember` / `warden_memory_context` → unchanged
- `warden_agent` / `warden_ask_marius` → unchanged  
- `warden_board` / `warden_post_task` → unchanged

## What Will Be Extended

- `brain_mcp_server.py` — add captain/dispatch/runs tools in place
- No new MCP server, no duplicate registries

## What Will Not Be Duplicated

- No new FastMCP instance
- No new `.mcp.json` entry
- No parallel tool registry endpoint (existing brain_mcp covers tool exposure)
