# Warden v2 — Handoff

Date: 2026-07-05 · Master: `b2fcdba` · Author: Fable 5 session, supervised by Matt.
Vision doc: [warden_v2_vision_alignment.md](warden_v2_vision_alignment.md) · Prior plan: [personal_ai_os_plan.md](personal_ai_os_plan.md)

All six phases (v2.1–v2.6) are implemented, tested, and merged to master. v2.7 (gated autonomy) was deliberately not built. Full suite at merge time: **794 passed, 1 skipped**.

---

## What is now in place

### v2.1 — Skill playbook engine ([#41](https://github.com/matthewjmcbridejr-code/mcharness/pull/41))

Skills are executable playbooks, not inert rows.

- `WorkbenchSkill` (src/warden/workbench.py) gained: `when_to_use`, `inspect_files[]`, `commands_allowed[]`, `commands_forbidden[]`, `proof_format`, `acceptance_checks[]`, `rollback_notes`, `report_template`. All optional/defaulted — pre-v2 skill JSON loads unchanged, no migration needed.
- New routes (src/warden/api.py): `GET/POST /api/mcharness/skills`, `GET /skills/{id}`, `POST /skills/{id}/dispatch`.
- Dispatch flow: playbook prompt (includes `CAPTAIN_ANTI_CLOBBER_GUARDRAIL`) → workbench thread + run → acceptance checks stored as **verifier evidence** (verdict `unknown`) → **open human proof gate** → CLI dispatch via existing `_execute_cli_dispatch_for_step`, or an honest `blocked` run when the private runner is off.
- Gotcha found: the old workbench skill CRUD routes lived on a router that was never mounted into the app. The mcharness routes above are the first reachable skill surface.

### v2.2 — Unified project view ([#42](https://github.com/matthewjmcbridejr-code/mcharness/pull/42), landed via #47)

- `GET /api/mcharness/projects/{id}/context` (src/warden/projects.py): one call returns project record, project-scoped memories, recent runs, **every open proof gate with run linkage**, worktrees, assigned agents, enabled skills. Subsystem failures degrade to `warnings[]`, never a 500.
- Known limitation: workbench runs are not project-scoped, so `runs` is recent-global and `pending_gates` is all-open-gates. Scoping runs to projects is the natural next improvement.

### v2.3 — UI consolidation ([#43](https://github.com/matthewjmcbridejr-code/mcharness/pull/43))

- **Canonical UI = `web/warden/app.html`** (Command Center). README and quickstart both point to `http://127.0.0.1:6969/web/warden/app.html`.
- `scripts/warden-up` — one start command (creates venv if missing, uvicorn on 6969, prints the URL).
- Runner Sessions ported into app.html as a read-only section (`web/warden/runners.js`); cleanup actions stay private-service-only.
- `index.html` and `command-deck.html` carry a **legacy banner** linking to app.html. They were NOT turned into redirect stubs on purpose: the entire Playwright suite (`tests/browser/warden-cockpit.spec.js`, 2,000+ lines) still targets index.html. Redirect only after that spec migrates.

### v2.4 — Memory unification ([#44](https://github.com/matthewjmcbridejr-code/mcharness/pull/44)) — executes personal_ai_os_plan PRs 2–6

- **Brain Inbox (PR2)**: `GET /warden/brain/inbox` + app.html section (`web/warden/inbox.js`) — reviewable feed of raw captures with per-item Promote/Discard. Nothing is promoted automatically.
- **Capture fidelity (PR3)**:
  - `WorkbenchMemory` gained `raw_content` (bounded 12k, redacted) + `raw_content_truncated`.
  - Vault notes: content bound raised 2,000 → 20,000 chars (`RAW_NOTE_CONTENT_MAX` in src/warden/brain/ingest.py), truncation flagged in body and frontmatter, **structured `url` frontmatter** on every ingested note.
  - Browser `browse` events accept optional `body_text`; extension capture is **opt-in** via `chrome.storage.local.warden_capture_body` (off by default, 12k cap) in browser-extension/content.js.
- **Linking (PR4)**: every ingest appends to vault `00-index.md` and adds a tag-based `## Related` wikilink section to new notes.
- **Promotion (PR5)**: `POST /warden/memory/{id}/promote` writes a vault note and sets `source_ref` (idempotent — second call is a no-op). `POST /warden/memory/{id}/discard` marks `forgotten`; never deletes files.
- **Plan context (PR6)**: `include_memory_context: bool` (opt-in) on `POST /captain/plan` enriches the LLM prompt with the memory context pack; the **persisted goal stays the user's original**. Captures inform planning, never trigger it.
- Note: `tests/test_warden_brain_source_fidelity.py` was flipped from pinning the old gaps to pinning the new behavior, per its own TODO comments.

### v2.5 — Bounded agent roles ([#45](https://github.com/matthewjmcbridejr-code/mcharness/pull/45))

- `SafetyProfile` gained `role`, `write_allowed`, `dispatch_allowed`, `allowed_actions[]`, `forbidden_actions[]`.
- Seven built-in envelopes (`ROLE_SAFETY_PROFILES` in workbench.py): **explorer, planner, builder, verifier, reviewer, deployer, archivist**. Always available via `list_safety_profiles()`; a stored profile with the same id overrides its built-in.
- `role_allows(profile, action)`: deny wins; a non-empty allowlist denies everything outside it (keyword substring match).
- Enforcement at skill dispatch (`role` param, default `builder`): read-only roles → 403 on dispatch; a role 403s any skill whose `commands_allowed` violate its envelope; constraints are also embedded in the worker prompt.
- Honest scope: enforcement is at the **dispatch boundary + prompt**, not runtime tool interception — a CLI agent in tmux is not syscall-sandboxed. Runtime interception would be the v3 hardening.

### v2.6 — Measurable loops ([#46](https://github.com/matthewjmcbridejr-code/mcharness/pull/46))

- Captain plans persist `check_command`, `max_dispatches` (0 = unlimited, cap 50), `dispatch_count`, `scope_paths[]`, `blocker`.
- **Budget**: every dispatch attempt (including runner-blocked ones) counts. Exhaustion calls `record_loop_blocker` (src/warden/captain_plans.py) — plan status `stopped`, pending steps stopped, blocker `{kind: budget_exceeded, reason, at}` recorded. No silent retry, no infinite loop.
- **Check command**: any step completion first runs the plan's check via `_run_plan_check_command` (src/warden/api.py) — shlex argv (no shell), 180s timeout, cwd pinned to the allowlisted repo. Failure → step `needs_review` + 409 with the command output.
- **Scope**: `scope_paths` and the check command are appended to every dispatch prompt.

---

## Test coverage added

| File | Covers |
|---|---|
| tests/test_warden_v2_skills.py | Skill CRUD, legacy JSON defaults, dispatch → run+gate+evidence, disabled/404 |
| tests/test_warden_v2_project_context.py | Project context aggregation, 404 |
| tests/test_warden_v2_ui_consolidation.py | Canonical UI wiring, banners, warden-up, docs URLs, sessions endpoint |
| tests/test_warden_v2_memory_unification.py | Inbox feed, promote (idempotent), discard, plan context flag |
| tests/test_warden_v2_roles.py | Role registration, allow/deny semantics, builder-rejects-deploy, explorer-can't-dispatch, deployer-allows-deploy |
| tests/test_warden_v2_loops.py | Loop field persistence, budget-halt-with-blocker, failing/passing check, scope-in-prompt |
| tests/test_warden_brain_source_fidelity.py | Rewritten: bounded body capture, 20k vault bound, url frontmatter, truncation flags, index entry |

Run everything v2: `pytest tests/test_warden_v2_*.py tests/test_warden_brain_source_fidelity.py -q` (33 tests).

---

## Merge history quirk (for archaeology)

The phases were stacked PRs #41→#46. After #41 merged and its branch was deleted, GitHub **closed #42 instead of retargeting it**. Recovery: #46→#45→#44→#43 were merged downward into `feat/warden-v2-v2.2`, then rollup [#47](https://github.com/matthewjmcbridejr-code/mcharness/pull/47) landed the superset on master. Every phase's diff is on master; #42's content arrived via #47.

A supervision proof gate for the v2.1 change itself was opened: run `run_v2-1-change-review-853a23`, gate `gate_81cc8371` — still open, decide it from the Proof panel.

---

## Not done / next

1. **v2.7 gated autonomy** — intentionally out of scope. Prereqs now exist (roles + budgets + check commands + gates); the design rule from the vision doc stands: auto-dispatch only low-risk steps where a verifier passes, gates unchanged for everything else.
2. **Happy-path dispatch untested** — test env has no private runner, so all dispatch tests exercise the honest blocked path. Do one manual smoke on the private service: create a skill, dispatch it, watch the gate open, approve, verify the tmux run.
3. **UI sections unverified in a browser** — Runner Sessions and Brain Inbox are API/static-tested only. `bash scripts/warden-up`, click both nav items.
4. **Playwright migration** — move warden-cockpit.spec.js selectors to app.html, then turn index.html/command-deck.html into real redirects (finishes fable5 audit #1).
5. **Project-scoped runs** — add `project_id` to workbench runs so `/projects/{id}/context` can filter runs/gates instead of returning recent-global.
6. **Pre-existing open PRs** #19–#24 (Jules security/test PRs) were untouched and still need review.
