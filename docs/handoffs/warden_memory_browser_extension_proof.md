# Handoff: Warden Memory Browser Extension — End-to-End Proof

**Date:** 2026-06-29  
**Branch:** `feat/marius-resident-core`  
**Commit:** `eab3b14`  
**Proof memory ID:** `proof-browser-ext-e2e-verified`

---

## What Was Tested

The full Warden memory pipeline was exercised end-to-end using a real Chrome session:

1. Chrome extension loaded from `browser-extension/` via `chrome://extensions → Load unpacked`
2. Real browsing activity performed (no synthetic data)
3. Extension batched events and flushed to Warden API
4. Memory Agent was asked to recall what was done
5. Memory Agent answered accurately from stored memories

---

## Extension Path

```
/home/matt/workspaces/warden/mcharness-public-export/browser-extension/
├── manifest.json   MV3, permissions: tabs, activeTab, webNavigation, storage, scripting, alarms, clipboardRead
├── background.js   Service worker — navigation capture, 15s flush queue
├── content.js      Injected on all pages — typing, selections, AI scrape, YouTube, GitHub, docs
├── popup.html      Status popup — queue depth, last flush, API status
└── popup.js
```

API ingest endpoint: `POST http://127.0.0.1:6969/api/mcharness/warden/browser/ingest`

---

## Activity Captured

The following real activity was captured without any manual input:

| Kind | Detail |
|---|---|
| `search` | `kali ai tools` (Google) |
| `search` | `was ask jeeves retired and what is the a big success?` (Google) |
| `search` | `warden memory architecture` (Google) |
| `browse` | Snyk homepage, AI Security Fabric page, AI AppSec cheatsheet |
| `browse` | Wikipedia — Comparison of search engines, Ask.com article |
| `browse` | Parseltongue 4.0 — Text Encoder, Decoder & Steganography Tool |
| `browse` | Hyperagent — Client Portal Mockup Refinement |
| `github` | GitHub OAuth flow (login + Snyk authorization) |
| `input` | Snyk project settings form — `autoDepUpgradeEnabled=true`, `autoFixPRs=true`, `pullRequestTestEnabled=true`, `snykCodeEnabled=true` |
| `input` | Project toggles — `agentshelf=on`, `marius-radar-foreman=on`, `matthewmcbride-landing=on`, `mcharness=on` |

Total memories at proof time: **68** (34 `user_note` from browser, 13 `proof`, 20 `agent_prompt`, 1 `agent_result`)

---

## What Memory Agent Reported Back

Query: `"What did I just do after installing the browser extension?"`

Memory Agent response (exact):

```
Warden Memory Snapshot — 2026-06-29 05:43 UTC

Branch: feat/marius-resident-core

Recent commits:
  • eab3b14 fix(browser-ext): fix service worker registration
  • 3766933 feat(browser): Chrome extension + browser ingest API
  • d97a367 fix(captain): enable Create Plan button

Recent browser visits:
  Sign in - Google Accounts, Sign in to GitHub

Stored memories:
  [user_note] [browsed] was ask jeeves retired and what is the a big success? - Google Search
  [user_note] [google search] was ask jeeves retired and what is the a big success?
  [user_note] [typed] agentshelf=on; marius-radar-foreman=on; matthewmcbride-landing=on; mcharness=on
  [user_note] [browsed] Wikipedia, the free encyclopedia
```

**The agent accurately recalled browser memories written from the extension — without being told what to look for.**

---

## What This Proves

**The Warden memory pipeline is end-to-end verified:**

```
Chrome tab activity
  → content.js captures (navigation, input, selection, search query, AI turns)
  → background.js batches in chrome.storage.local
  → flush() POSTs to /api/mcharness/warden/browser/ingest every 15s
  → WorkbenchStore.create_memory() writes user_note JSON to _mctable/workbench/memories/
  → Memory Agent loads recent memories as context
  → Memory Agent answers accurately about what happened
```

This is the core Warden value proposition working as designed:
> Warden captures everything you do and lets you ask about it later.

---

## Known Limitations

| Limitation | Detail |
|---|---|
| ChatGPT DOM scraper | Built in `content.js` but untested against current ChatGPT UI — OpenAI updates their DOM frequently |
| Claude.ai DOM scraper | Same — needs live validation |
| `--plain` flag on `warden-chat mem` | Flag exists on top-level parser only, not on `mem` subparser — causes arg error |
| Search query dedup | Same query searched twice gets deduplicated (by URL hash) — correct behavior but means no frequency tracking |
| Incognito not covered | Extension won't run in incognito unless explicitly enabled in chrome://extensions |
| Firefox not covered | Extension is Chrome/Chromium only |
| Memory watcher daemon not running | `warden-memory-watcher` systemd service was not active during this test — git hooks + Chrome polling handled capture |

---

## Next Recommended Improvements

1. **Fix `--plain` on `warden-chat mem`** — add `p_mem.add_argument("--plain", ...)` in `scripts/warden-chat`
2. **Test ChatGPT/Claude DOM scrapers** — open a real conversation, check browser memory is written with `kind=ai_conversation`
3. **Start memory watcher daemon** — `systemctl --user enable --now warden-memory-warden` so git commits + shell history also flow automatically
4. **Wire `traces.record()`** — gateway traces endpoint always returns `[]`; hook into `ProviderGateway.chat()` call path
5. **Memory search in UI** — Memory Chat tab could show a live count of what types of memories exist and allow filtering by kind/tag
6. **Frequency + recency signals** — same URL visited 5× in a day should rank higher in Memory Agent context than a one-off visit
7. **Add `warden-chat mem --plain` fix** to next commit
