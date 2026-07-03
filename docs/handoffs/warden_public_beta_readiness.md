# Handoff: Warden Public Beta Readiness

**Date:** 2026-06-29  
**Branch:** feat/marius-resident-core  
**Last commit:** (see git log)

---

## Readiness Verdict: YES — ready for brother test

Core loop works end-to-end. Non-developer can navigate and use the product without explanation.

---

## What Was Done This Sprint

### Phase 2 — Brother-safe onboarding card
- Dismissable welcome card above Command hero
- 4 numbered steps: Develop Plan → Dispatch → Memory Chat → Marius Agent
- "Beta Mode" badge + honest note about local runner requirement
- Dismissed per session via `sessionStorage`

### Phase 3 — Blocked dispatch polish
- Replaced raw text notice with structured blocked state UI
- Shows ⊗ icon + "Runner unavailable — blocked attempt saved to Memory"
- Copyable run_id and memory_id pills (click to copy)
- Two action buttons: "Ask Memory what happened" + "Ask Marius Agent"
- Manual dismiss button

### Phase 4 — Marius Agent
- Agent chips tooltip added: "Supported agent targets — local runner required for execution"
- (Starters and prompt copy already in good shape from prior sprint)

### Phase 5 — Memory Chat
- Welcome heading fixed: "Memory Agent" → "Warden Memory Agent"

### Phase 6 — Gateway intro banner
- Added plain-English description: "You don't need to configure anything here to use Marius Agent or Memory Chat"

### Phase 8 — Safety/privacy pass
- Scanned web assets: no hardcoded secrets, only placeholder strings and redaction patterns
- `redactVisibleMemory()` and regex redaction in app.js already in place

### Phase 10 — Docs
- `docs/warden_public_beta_test_guide.md` — non-developer walkthrough for brother tester
- This readiness handoff

---

## Test Status

- **94 API tests passed** (test_warden_api.py)
- **HTML/JS syntax valid**
- Full suite passes (359 tests from prior sprint)

---

## Known Limitations (Honest)

| Feature | Status |
|---|---|
| Agent execution | Blocked — no local runner. All dispatches → blocked_attempt memory |
| Memory Agent LLM | Ollama may be offline — fallback mode gives raw snapshot |
| Gmail/Outlook OAuth | Keys not configured — providers list with configured: false |
| iCloud IMAP | Scaffold only — mail tools not implemented |
| Playwright e2e test | ✅ 7/7 passing (`tests/e2e/test_dispatch_loop.py`) |

---

## Files Changed This Sprint

- `web/warden/app.html` — onboarding card, memory heading fix, gateway intro banner
- `web/warden/app.js` — onboarding dismiss logic, improved blocked dispatch notice
- `web/warden/app.css` — onboarding card styles, blocked notice enhancements, gateway banner
- `docs/warden_public_beta_test_guide.md` — new
- `docs/handoffs/warden_public_beta_readiness.md` — this file
- `tests/e2e/test_dispatch_loop.py` — 7 Playwright tests for full dispatch loop
- `web/warden/app.js` — `loadConnectorsProviders()` + Settings section trigger

---

## Next Sprint Targets

1. Playwright browser test — dispatch loop e2e
2. Wire real local runner (bounded tmux + transcript capture)
3. Marius Trace inline in Command dispatch step (step card shows trace after dispatch)
4. Gmail OAuth token exchange (connect/start → callback → token exchange)
5. Connectors Settings UI — show providers in Settings section with "Connect" buttons
