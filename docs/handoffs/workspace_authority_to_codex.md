# Workspace Authority Handoff

**From:** Claude  
**To:** Codex  
**Date:** 2026-06-27  
**Branch:** `feat/marius-resident-core`

---

## Problem Fixed

Agents were coding in scattered repos and losing source-of-truth context.

- Codex worked in `/home/matt/Documents/Warden`
- Claude worked in `/home/matt/workspaces/warden/mcharness-public-export`
- Command Deck UI existed in Codex's repo; backend existed in Claude's repo
- Codex reconciled them into the canonical repo (commit `16e131d`)

Warden Workspace Authority now prevents this by making the canonical workspace explicit and machine-readable via API.

---

## Canonical Repo

```
/home/matt/workspaces/warden/mcharness-public-export
```

Branch: `feat/marius-resident-core`  
Live service: `http://127.0.0.1:6969`

---

## Known Scratch Repos

| Path | Role | Safe to Edit |
|------|------|-------------|
| `/home/matt/Documents/Warden` | scratch_or_clone | ❌ No |

---

## New Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/mcharness/warden/workspaces` | List all registered projects |
| `GET` | `/api/mcharness/warden/workspaces/{project_id}` | Get project workspace info |
| `POST` | `/api/mcharness/warden/workspaces/resolve` | Classify a cwd against a project |
| `POST` | `/api/mcharness/warden/workspaces/bootstrap` | Full agent bootstrap packet |

Bootstrap response includes:
- `canonical_repo` — where to code
- `code_here` — safe worktrees
- `do_not_code_here` — scratch/clone paths
- `live_services` — proof service URL/port
- `proof_commands` — commands to verify work
- `branch_policy` — preserve_main, no_force_push
- `agent_start_rules` — rules every agent must follow
- `cwd_classification` — is the calling cwd safe?
- `warnings` — non-empty if cwd is wrong
- `recommended_next_action` — plain-English next step

---

## Command Deck Service Proof

```
page:             200
state:            200
proofs:           200
relay:            200
events:           200
seed:             201
workspaces/warden: 200
```

HTML: `http://127.0.0.1:6969/web/warden/command-deck.html` → 200  
Command Deck Workspace Authority panel now visible in UI.

---

## Workspace Authority Proof

```bash
# Canonical cwd — no warnings
curl -X POST http://127.0.0.1:6969/api/mcharness/warden/workspaces/bootstrap \
  -d '{"project_id":"warden","cwd":"/home/matt/workspaces/warden/mcharness-public-export"}'
# → warnings: []

# Scratch cwd — WARNING shown
curl -X POST http://127.0.0.1:6969/api/mcharness/warden/workspaces/bootstrap \
  -d '{"project_id":"warden","cwd":"/home/matt/Documents/Warden"}'
# → warnings: ["WARNING: You are in '/home/matt/Documents/Warden' which is NOT canonical. Use: /home/matt/workspaces/warden/mcharness-public-export"]
```

---

## Tests Run

```
60 passed in 0.76s
```

Files:
- `tests/test_warden_workspace_authority.py` — 22 tests
- `tests/test_warden_command_deck.py` — from Codex reconciliation
- `tests/test_warden_cockpit_static.py` — includes command-deck.html checks
- `tests/test_warden_risk_gate.py` — 14 tests
- `tests/test_warden_agent_dispatcher.py` — 7 tests
- `tests/test_warden_daily_brief.py` — 5 tests

---

## Remaining Work

1. **Workspace panel in browser** — the `command-deck.html` Workspace Authority panel loads from `/api/mcharness/warden/workspaces/warden` — test visually in browser after reload
2. **Notion sync** (mega prompt item 6) — dry-run Warden board → Notion Master Inbox
3. **Branch-aware memory** (item 7) — add repo/branch/commit metadata to `warden_remember`
4. **Context packs improvement** (item 10) — structured 12-section agent brief

---

## Next Codex Task

**Make all future Codex prompts start by calling Workspace Authority.**

At the start of every Codex prompt or task, Codex must:

1. Call `GET /api/mcharness/warden/workspaces/warden` or `POST /workspaces/bootstrap` with the current `cwd`
2. If `safe_to_edit` is `false` or `warnings` is non-empty — **STOP. Do not make edits. Report the drift and correct the path first.**
3. If `safe_to_edit` is `true` — proceed with the task using `proof_commands` from the response to verify work.

This is the root-cause fix for scattered agent work.

Suggested Codex system prompt addition:
```
Before editing any file, call:
  curl -X POST http://127.0.0.1:6969/api/mcharness/warden/workspaces/bootstrap \
    -H "Content-Type: application/json" \
    -d "{\"project_id\":\"warden\",\"cwd\":\"$(pwd)\"}"
If safe_to_edit is false, do not proceed. Switch to the canonical_repo path first.
```
