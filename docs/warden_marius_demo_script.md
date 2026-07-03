# Warden — Marius Command Center Demo Script

**Updated:** 2026-06-29  
**Branch:** feat/marius-resident-core  
**Story:** Local-first AI command center where Marius Agent drives the session.

---

## What Warden Is

Warden is a local-first AI command center. The product loop:

**Open Warden → Marius Agent → Create Plan → Dispatch Step → Capture Proof or Blocked Attempt → Save Memory → Marius Trace shows what happened → Warden Memory Agent can recall it → Marius Agent uses that memory in the next answer**

Key components:
- **Marius Agent** — main command/chat surface (routes to git, GitHub, memory, web)
- **Warden Memory Agent** — dedicated memory worker; reports reads/writes into Marius Trace
- **Marius Trace** — per-response trace showing context, tools, memory ops, proof, blockers
- **Warden MCP** — exposes approved Warden/Marius tools to any Claude agent
- **Warden Connectors** — safe account connection layer for Gmail, Outlook, iCloud Mail

Gateway is infrastructure, not the headline.

---

## Prerequisites

```bash
curl http://127.0.0.1:6969/api/mcharness/health
# Expected: {"ok": true, ...}
```

No cloud key required for core loop. OpenRouter key unlocks richer plans.

---

## Demo (7 minutes)

### 1. Open and orient (30s)

```
http://127.0.0.1:6969/web/warden/app.html
```

- Default: **Command** tab
- Nav: Command | Marius Agent | Memory Chat | Gateway Status
- Single section visible at a time

### 2. Ask Memory what's happening (1m)

Click **Memory Chat**, type:
> What have I been working on?

CLI version:
```bash
scripts/warden-chat mem "What have I been working on?" --plain
```

Shows: recent commits, browser visits, last captures — whatever Warden has seen.

### 3. Create a Captain Plan (1m)

Back in **Command**, enter:
> Build a feature to recall the latest blocked dispatch from memory

Click **Develop Plan**.

Renders 3–5 steps with agent, status, Dispatch Step button.

API proof:
```bash
curl -sS http://127.0.0.1:6969/api/mcharness/captain/plan \
  -H 'Content-Type: application/json' \
  -d '{"goal":"Build a feature to recall the latest blocked dispatch from memory","repo_id":"mcharness-public-export","lane_id":"codex_cli"}' | jq .plan_id
```

### 4. Dispatch a Step (1m)

Click **Dispatch Step** on Step 1.

Runner is not available → honest blocked state:
- UI: "Runner unavailable — blocked attempt saved to Memory"
- run_id and memory_id shown under step

API proof:
```bash
curl -sS -X POST "http://127.0.0.1:6969/api/mcharness/captain/plans/PLAN_ID/steps/step_1/dispatch" \
  | jq '{ok, blocked, run_id, memory_id, message}'
```

### 5. Ask Memory what the last agent run did (1m)

```bash
scripts/warden-chat mem "What did the last agent run do?" --plain
```

Expected output:
```
Latest Agent Run:
  Status: blocked_attempt
  Captain dispatch blocked — runner unavailable. Step: ...
  Run ID: blocked-xxxxxxxx
  Plan: plan_xxxxxxxx
  Lane: codex_cli
  Reason: runner_unavailable
  Memory ID: dispatch-xxxxxxxxxxxx
```

### 6. Open Marius Agent and ask about the blocker (1m)

Click **Marius Agent**, type:
> What got blocked in my last captain dispatch?

Marius pulls from memory context + git.  
**Marius Trace** panel (right side) shows: memory_read → tool_action steps — what ran.

### 7. Show connector platform (30s)

```bash
curl -sS http://127.0.0.1:6969/api/mcharness/warden/connectors/providers | jq '.providers[] | {provider_id, configured}'
```

Shows Gmail, Outlook, iCloud — all `configured: false` without OAuth keys.

When keys are added: connect/start returns OAuth auth_url, callback validates state.

---

## Proof Commands

```bash
# Core loop proof
curl -sS http://127.0.0.1:6969/api/mcharness/health | jq .
curl -sS "http://127.0.0.1:6969/api/mcharness/memories?limit=5" | jq '.memories[] | {kind, source, summary}'
scripts/warden-chat mem "What did the last agent run do?" --plain
scripts/warden-chat mem "What plan did I just create?" --plain

# Connector proof
curl -sS http://127.0.0.1:6969/api/mcharness/warden/connectors/providers | jq .
curl -sS http://127.0.0.1:6969/api/mcharness/warden/connectors/accounts | jq .
```

---

## What's Working (v0)

| Feature | Status |
|---|---|
| Warden API + health | ✅ |
| Captain Plan (local preview) | ✅ |
| Dispatch → blocked_attempt memory | ✅ |
| Memory Agent recall (latest run) | ✅ |
| Marius Agent UI rename | ✅ |
| Marius Trace in responses | ✅ |
| Single-section navigation | ✅ |
| Browser extension memory capture | ✅ |
| Connector scaffold (providers/accounts/OAuth start) | ✅ |
| MCP brain server (captain/dispatch/run tools) | ✅ |

## Known Blockers

| Blocker | Impact |
|---|---|
| tmux/codex runner not configured | Dispatch always produces blocked_attempt |
| Ollama offline → Memory Agent fallback mode | Raw snapshot instead of LLM answer |
| OAuth client IDs not set | Gmail/Outlook connect returns `configured: false` |
| iCloud IMAP not wired | Store/oauth present but mail tools not implemented |

---

## Next Sprint Targets

1. Wire real local runner with bounded timeout + transcript capture
2. Marius Trace inline in Command dispatch step UI
3. iCloud IMAP connector with app-specific password vault
4. Playwright browser test for the full dispatch loop
5. Gmail OAuth token exchange + mail.search
