# Handoff: Warden — Marius Agent + Trace + MCP + Connectors Sprint

**Date:** 2026-06-29  
**Branch:** feat/marius-resident-core  
**Last commit:** 5bfca4f feat(warden): add MCP extension, connector platform scaffold, and connector routes

---

## What Was Done This Sprint

### Phase A — Integrity + API restart
- Verified 55a799f fixture deletions were intentional (test-generated runner fixtures, now gitignored)
- Restarted Warden API to pick up dispatch code (was running old binary from Jun28)
- Fixed pre-existing grounding test (assert content that actually exists in AGENTS.md)

### Phase B — Dispatch loop proved
- `POST /captain/plans/{plan_id}/steps/{step_id}/dispatch` working
- Returns: `{ok: true, blocked: true, run_id, memory_id, message}`
- Memory written: `blocked_attempt` kind, `captain_dispatch` source, full metadata

### Phase C — Memory recall hardening (`f8470d6`)
- `_latest_dispatch()` in memory_agent.py: finds newest blocked_attempt/agent_result from dispatch sources
- `MemoryContext.latest_dispatch` field: always surfaced first in fallback answers
- `_RUN_SIGNALS` / `_DISPATCH_KINDS` boost in `search_memories` for "last agent run" queries
- Fallback structured answer opens with "Latest Agent Run" block for run queries
- Fixed `/memory/recent` → actual endpoint is `/memories`

### Phase D — Marius Agent rename (`f6c2123`)
- Nav button: "Warden Chat" → "Marius Agent"
- Section heading: "Warden Agent" → "Marius Agent"
- Tool trace pane: "Tool Calls" → "Marius Trace"
- Memory section: "Memory Agent" → "Warden Memory Agent" + trace note
- MCP inventory doc: `docs/handoffs/warden_mcp_inventory.md`

### Phase E — Marius Trace (`3bb7124`)
- `TraceStep`, `MarusTrace` dataclasses in agent.py
- `_build_trace()`: builds trace dict from tools_used + sources + fallback
- `AgentResponse.trace` field (optional, additive)
- All run_agent return paths produce trace
- `/warden/agent/chat` returns `trace` field
- Frontend `renderTrace(toolsUsed, trace)` uses Marius Trace steps when available
- CSS: `wa-trace-skipped`, `wa-trace-blocked`, `wa-trace-error`

### Phase F — MCP extension + Connector platform (`5bfca4f`)
- MCP brain server: 6 new tools (captain plan/recent/dispatch, run get, connector providers/accounts)
- `src/warden/connectors/`: models, store, registry, oauth, __init__
- 3 providers: Gmail (OAuth2), Outlook (OAuth2), iCloud (app_password)
- 8 connector tools: read_only / write_gated / destructive_blocked risk levels
- Token vault: server-side only, 600 perms, never exposed to agents or API responses
- `.env.warden-connectors.example` with all env var placeholders
- API: 5 connector endpoints (providers, accounts, connect/start, callback, disconnect)
- Tests: 8 new (providers unconfigured, accounts empty, Gmail connect configured/unconfigured, callback rejects invalid state, token redaction, Marius Trace field)

---

## Architecture State

```
Marius Agent (UI + API)
  └─ /warden/agent/chat → run_agent → AgentResponse{trace}
       └─ trace: {trace_id, agent, steps: [{type, label, status, detail}]}

Warden Memory Agent
  └─ /warden/memory-agent/chat → memory_agent.chat
       └─ gather_context → _latest_dispatch() → MemoryContext{latest_dispatch}

Warden MCP (stdio, warden-brain)
  └─ 23 tools total (17 original + 6 new)
       └─ captain: plan, recent_plans, dispatch_step
       └─ runs: run_get
       └─ connectors: providers, accounts

Warden Connectors
  └─ /warden/connectors/* (5 endpoints)
       └─ providers: Gmail/Outlook/iCloud with OAuth or app_password
       └─ store: server-side token vault (never in API responses)
       └─ oauth: start_oauth_flow, validate_callback_state
```

---

## Test Status

- **359 passed, 1 skipped, 0 failed** (full suite)
- Pre-existing grounding test failure fixed
- 8 new connector + trace tests

---

## What Remains

| Item | Notes |
|---|---|
| Real local runner dispatch | tmux/codex not configured — blocked_attempt is current v0 |
| Marius Trace in Command UI | Backend done; Command step UI still shows raw run_id/memory_id |
| Gmail OAuth token exchange | connect/start → auth_url works; callback → token exchange not wired |
| iCloud IMAP mail tools | store/oauth scaffolded; mail search/read not implemented |
| Playwright browser test | dispatch loop e2e test not yet written |
| Mail send (write_gated) | Blocked by default; requires WARDEN_MAIL_ALLOW_SEND=1 + confirmation |

---

## Continuing Work

Read `docs/warden_marius_demo_script.md` for the demo flow.  
Read `docs/handoffs/warden_mcp_inventory.md` for MCP architecture.  
Read `AGENTS.md` for repo conventions.

Next agent: start with `git log --oneline -8` and `curl http://127.0.0.1:6969/api/mcharness/health`.
