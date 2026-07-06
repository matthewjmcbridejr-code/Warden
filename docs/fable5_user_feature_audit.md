# Fable 5 User Feature Audit

Date: 2026-07-03 · Repo: `mcharness-public-export` (branch `feat/marius-resident-core`)
Method: static inspection of README, AGENTS.md, docs/, `src/warden/`, `web/warden/`, `tests/`, pending git diff. No code was changed. Facts below marked **[verified]** were read from files; items marked **[inference]** are product judgment.

---

## 1. Executive Verdict

**What works [verified]:** This is a real product with unusual depth for a personal project. The backend is broad: ~180 FastAPI routes in `src/warden/api.py` (5,214 lines) covering Captain planning, agent dispatch, runner sessions, proof gates, run history/reports, memory (recall/remember/search), Warden Brain (vault, ingest, Google mirror, ask), mail connectors (Gmail/iCloud app-password), model gateway with routing policy + traces, and a Chrome-extension browser-ingest endpoint. There are 84 test files plus Playwright e2e (`tests/browser/warden-cockpit.spec.js`, `tests/e2e/test_dispatch_loop.py`). There is already a demo script (`docs/warden_demo_script.md`), a demo-seed endpoint (`POST /warden/command-deck/demo-seed`), onboarding copy in `app.html`, and suggestion chips.

**What is weak [verified + inference]:**
1. **Two competing UIs.** `web/warden/index.html` ("Control Room", 10 nav sections, README points here on :8125) and `web/warden/app.html` ("Command Center", demo script points here on :6969) overlap heavily. `command-deck.html` is a third surface. A new user or demo viewer cannot tell which is the product.
2. **Port/entry-point confusion.** README says 8124/8125; quickstart and demo script say 6969. First-run friction is the top adoption killer here.
3. **Memory is the wow feature but its UX is buried** — it lives behind a nav item and a chat box; there is no "here is everything Warden captured today" view a buyer instantly understands.
4. **No single first-run path**: quickstart requires venv + uvicorn + Chrome extension + systemd watcher, four manual steps.

**Verdict:** Demo-ready with a script and a prepared machine (the demo doc proves this was done). **Not yet sellable or self-serve**: no packaged start command, ambiguous entry point, no first-run experience without pre-seeded personal data. The next work should be consolidation and first-run polish, not new capabilities.

---

## 2. Current User Workflows Found

| Workflow | Entry point / files | What user can do | Current weakness | Demo 1–5 |
|---|---|---|---|---|
| Memory Chat ("what did I do?") | `app.html` → `memory.js`, `/api/mcharness/warden/memory-agent/chat` | Ask natural-language questions over captured git/browser/shell activity | Depends on watcher + extension being installed; empty without data | **5** (with data) |
| Warden Agent chat | `app.html` → `agent.js`, `/warden/agent/chat` | Tool-calling agent reads repo, git, memory | No visible tool-call trace in UI to prove "it's not guessing" | 4 |
| Captain plan → dispatch → complete | `index.html`/`app.js`, `/captain/plan`, `/captain/plans/{id}/steps/{id}/dispatch` | Develop a 3–5 step plan, dispatch steps to agents, mark complete/revise | Multi-screen, manual; Jules "planning only"; Codex needs private flags | 3 |
| Proof gates / evidence | `proof_gates.py`, `/gates/*`, `/evidence/*`, Evidence + Proof Gates nav | Approve/block runs, attach evidence, export run report markdown | Split across two UIs; no notification when a gate is waiting | 3 |
| Runner sessions | `runner_sessions.py`, `/sessions/*` routes | Start/stop tmux Codex runner, view transcript, convert transcript to evidence | Only works with private flags on; status is poll-based | 2 |
| Command Deck task board | `command-deck.html/js`, `/warden/command-deck/*` | Post tasks, claim, attach proof/failure/handoff, demo-seed | Third parallel UI; unclear relation to Missions/Tasks | 3 |
| Brain (vault/ask/ingest) | Settings → brain card, `/warden/brain/*`, `brain_ingest_cli.py` | Init vault, ingest files/URLs, search, ask, Google mirror | Buried in Settings; no browse-the-vault view | 3 |
| Mail search | `/warden/mail/*`, `mail/` module, Settings mail panel | Connect Gmail/iCloud via app password, search, read messages | Read-only surface hidden in Settings; no inbox view | 2 |
| Model Gateway status | `gateway.js`, `/warden/model-gateway/*` | View aliases, route-preview, traces, privacy guard | Good internal tool; unexplained to a buyer | 3 |
| Marius CLI / chat | `scripts/marius`, `/agents/marius/*` | Terminal assistant with model switch, bench, memory | Parallel to Warden Agent — story overlap | 3 |
| Browser capture | `browser-extension/`, `POST /warden/browser/ingest` | Silent capture of URLs, searches, typed text | Manual unpacked-extension install; no capture-health indicator in UI | 4 |

---

## 3. Highest-Leverage Improvements (ranked)

1. **One canonical UI + one start command**
   - Problem: user/buyer can't tell whether the product is `index.html`, `app.html`, or `command-deck.html`, or which port to use.
   - Why: every demo, doc, and test currently hedges between three surfaces. This is the single biggest clarity multiplier.
   - Files: `web/warden/index.html`, `app.html`, `app.js`, `control-room.js`, `README.md`, `docs/quickstart.md`, new `scripts/warden-up`.
   - Effort **M** · Risk **Low** · Impact **High**
   - Accept: `bash scripts/warden-up` starts the API and prints one URL; README/quickstart/demo script all name the same URL; old pages redirect.

2. **"Today" timeline view for Memory**
   - Problem: the killer feature (automatic capture) has no glanceable proof; you must ask a chat question to see it.
   - Why: a reverse-chronological feed of commits, pages, searches, shell events is the demo money-shot and the daily-use hook. Data already exists via `/mcharness/memories` and `worklog.py`.
   - Files: `web/warden/memory.js`, `app.html`, possibly a `GET /memories?since=` filter in `api.py`.
   - Effort **M** · Risk **Low** · Impact **High**
   - Accept: opening Memory shows today's events grouped by hour/source with counts; empty state explains how to enable capture.

3. **First-run onboarding checklist with live capture health**
   - Problem: fresh install shows empty screens; quickstart is 4 manual steps with no in-app confirmation.
   - Files: `app.html` onboarding card (exists at `#warden-onboarding-toggle`), new `GET /warden/setup/status` aggregating watcher/extension/Ollama/brain health (reuse `/health`, `/memory/health`, `/warden/brain/health`).
   - Effort **M** · Risk **Low** · Impact **High**
   - Accept: fresh profile shows a 4-item checklist; each item flips green when its subsystem reports healthy.

4. **Demo mode that seeds the whole app, not just Command Deck**
   - Problem: `demo-seed` only creates a Command Deck task; Memory, Runs, Evidence stay empty on a clean machine.
   - Files: extend `post_command_deck_demo_seed` in `api.py:3898` or add `/warden/demo/seed`; wire to the existing `demo-mode-banner` in `index.html:15`.
   - Effort **S/M** · Risk **Low** (local writes only) · Impact **High** (demo)
   - Accept: one POST populates memories, a plan, a run with evidence, and a pending gate; banner shows "Demo data".

5. **Pending-gate notification surface**
   - Problem: proof gates are the supervision story, but nothing tells the operator a gate is waiting.
   - Files: `/gates/recent` already exists; add badge count on Proof Gates nav + topbar chip in `app.js`/`control-room.js`.
   - Effort **S** · Risk **Low** · Impact **Med/High**
   - Accept: creating a gate makes a badge appear within one refresh cycle; deciding it clears the badge.

6. **Agent chat tool-trace panel**
   - Problem: demo claim "it's not guessing" is unprovable in the UI; tool calls are invisible.
   - Files: `agent.py` (loop already knows its tool calls), `/warden/agent/chat` response shape, `agent.js` render.
   - Effort **M** · Risk **Low** · Impact **High** (demo proof)
   - Accept: each agent reply shows an expandable list of tools called with args and truncated results.

7. **Daily brief delivered in-app**
   - `daily_brief.py` exists **[verified]** but has no visible UI surface in `app.html`. Morning "here's what happened yesterday + what's pending" card at top of Command Center.
   - Files: `daily_brief.py`, route in `api.py`, card in `app.html`/`app.js`.
   - Effort **S/M** · Risk **Low** · Impact **Med** (retention/daily habit → sellable)
   - Accept: Command Center shows a dated brief; regenerate button works.

8. **Run report download/export button everywhere**
   - `/runs/{run_id}/report` markdown export exists; make it a visible "Export report" button on every run row and gate view; add "copy as PR comment" variant.
   - Files: `app.js`, `control-room.js`.
   - Effort **S** · Risk **Low** · Impact **Med**
   - Accept: clicking Export downloads `run-<id>-report.md` with the same content the API returns.

9. **Mail: minimal inbox view instead of Settings-buried search**
   - `/warden/mail/search` + message read exist; give Mail its own section with account chips, search box, result list, message pane. Read-only (send-draft stays out of scope).
   - Files: `app.html` (nav already has a Mail entry pointing into Settings), new `mail.js`.
   - Effort **M** · Risk **Low** (read-only) · Impact **Med**
   - Accept: search returns rendered results; clicking opens the message body.

10. **Consolidate/retire duplicate workspace copies**
    - Problem: five sibling repos (`warden-memory-v1*`, `warden-command-deck-next`, etc.) plus `_repo_audit_*` and `_patch_backups` in the workspace; `warden-command-deck-next` has an AGENTS.md that itself says work belongs in `mcharness-public-export`. Confusion tax on every agent/session.
    - Files: workspace level; `repo_workspace_cleanup_plan.md` already exists **[verified]** — execute it.
    - Effort **S** (archive/move, no deletes) · Risk **Low** if archived not deleted · Impact **Med** (velocity, not demo)
    - Accept: workspace contains one active repo plus an `archive/` directory; AGENTS.md updated.

---

## 4. "Build Next" Recommendation (top 3)

### A. One canonical UI + `warden-up` (improvement #1)
- **User story:** As a new user, I run one command and open one URL, and I'm in the product.
- **Behavior:** `scripts/warden-up` activates `.venv`, starts uvicorn on one agreed port (recommend keeping 6969 since demo script and quickstart use it), prints the URL. `app.html` becomes canonical; `index.html` and `command-deck.html` either redirect or their unique panels (Proof Gates, Runner Sessions, Command Deck board) migrate into `app.html` sections.
- **Plan:** (1) inventory panels unique to `index.html`/`command-deck.html`; (2) port the 2–3 that matter (Proof Gates, Runner Sessions) into `app.html` sections — nav slots already exist; (3) redirect stubs; (4) update README/quickstart/demo script; (5) add `scripts/warden-up`.
- **Tests:** update `tests/browser/warden-cockpit.spec.js` selectors to the canonical page; new test asserting redirect from old pages; smoke `scripts/warden_smoke.sh` still passes.
- **Proof:** one URL in all docs; Playwright run green; screenshot of consolidated nav.

### B. Memory "Today" timeline (improvement #2)
- **User story:** As the operator, I open Warden and immediately see everything it captured today, grouped by source, without asking a question.
- **Behavior:** Memory section defaults to a Timeline tab: hour-grouped entries with source icons (git / browser / shell / manual), filter chips per source, count summary ("47 events · 12 commits · 30 pages · 5 searches"), each entry expandable. Chat remains as a second tab.
- **Plan:** (1) confirm `GET /mcharness/memories` supports since/source filtering, add query params if not (`workbench.py`); (2) build timeline render in `memory.js`; (3) empty state linking to the onboarding checklist.
- **Tests:** API test for since/source filters (pattern from `test_brain_api.py`); Playwright test seeding two memories and asserting grouped render + filter behavior.
- **Proof:** screenshot of populated timeline; curl output of filtered API call.

### C. Whole-app demo seed + demo banner (improvement #4)
- **User story:** As the founder demoing on any machine, I click "Load demo data" and every section has believable content in under 5 seconds.
- **Behavior:** `POST /api/mcharness/warden/demo/seed` writes: ~30 memories across sources spanning "today", 1 Captain plan with 3 steps (1 complete with evidence), 1 run with report, 1 pending proof gate, 2 Command Deck tasks. All records tagged `demo: true`; existing `demo-mode-banner` shows; `POST /warden/demo/clear` removes only demo-tagged records.
- **Plan:** (1) fixture module `src/warden/demo_seed.py` reusing `WorkbenchStore`, `captain_plans`, `run_history`, `proof_gates` writers; (2) two routes; (3) button in Settings + auto-offer in the empty-state onboarding card.
- **Tests:** API test: seed → each list endpoint non-empty → clear → demo records gone, non-demo untouched. E2E: seed then assert Memory timeline and gate badge populate.
- **Proof:** before/after screenshots; test output.

---

## 5. Quick Wins Under 2 Hours

- **Fix README/quickstart port mismatch** (8125 vs 6969) — pure copy, kills the #1 first-run trap. [`README.md`, `docs/quickstart.md`]
- **Commit the pending `api.py` health fix** — the cheap-`/health` change (static counts instead of git shell-outs) is already in the working tree and directly fixes the browser extension's 2s timeout. Test + commit it.
- **Nav label consistency**: `index.html` says "Control Room/Missions", `app.html` says "Command Center/Tasks" — pick one vocabulary.
- **Empty states with next-action buttons** for Memory, Runs, Evidence ("No runs yet — Develop a plan to start one").
- **Gate badge count** (improvement #5) is plausibly under 2h given `/gates/recent` exists.
- **Suggestion chips per section**, not just Command Center — Memory chat gets "What did I search today?" etc. (chips pattern exists in `app.html:99–102`).
- **"Export report" button** on run rows (route exists at `api.py:3443`).
- **Capture-health chip in topbar**: green/grey dot from `/memory/health` telling you the watcher/extension are alive.
- **Hide dead controls**: `#use-codex-directly` and `#marius-test-drive-btn` ship with `display:none` inline styles — remove or gate them properly.

## 6. Risks / Bad Ideas To Avoid

- **Don't build a fourth UI surface.** The problem is consolidation, not another dashboard.
- **Don't automate dispatch/auto-merge.** The safety posture (manual gates, no arbitrary shell, runner-disabled public port) is the product's differentiator; autonomy erodes the pitch.
- **Don't build billing yet [inference].** Single-operator local-first tool; a pricing page before self-serve install works is fake work.
- **Don't expand mail to sending** from the UI; read-only search is safe and sufficient for the story.
- **Don't chase Jules/multi-agent breadth** — Jules is planning-only today; deepening the Codex loop beats adding half-connected agents.
- **Don't ship the Chrome extension's silent capture to anyone else without consent UX** — "captures every keystroke/clipboard" is fine for the owner, a liability in a sellable product.
- **Housekeeping risk:** `google-cloud-sdk/` and a gcloud tarball are sitting in the repo root — bloats clones; move out (non-destructively) before sharing the repo.

## 7. Suggested Implementation Branch

- Branch: `feat/canonical-ui-first-run`
- First commit: `feat(web): consolidate on app.html as canonical UI with warden-up start script`

---
*Report generated by Fable 5 audit. No code changed; one pre-existing uncommitted diff in `src/warden/api.py` was observed and left untouched.*
