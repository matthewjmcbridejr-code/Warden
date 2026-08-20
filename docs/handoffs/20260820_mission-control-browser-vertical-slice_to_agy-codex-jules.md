# Warden Mission-Control Redesign — Browser Vertical Slice

**Handoff ID:** `20260820_mission-control-browser-vertical-slice_to_agy-codex-jules`  
**Status:** Ready for implementation after GUI ADR is brought onto current `master`  
**Primary audience:** Agy / architecture lead, Codex / implementation lead, Jules / independent reviewer  
**Repository:** `matthewjmcbridejr-code/Warden`  
**Current runtime baseline at handoff authoring:** `master` = `edb2ef8bc5ae26fa5e9d3693c745554de1f0908f`  
**Related PRs:** GUI ADR PR #58, Computer Use PR #59 (merged)  
**Target implementation branch:** `feat/mission-control-browser-vertical-slice`  
**Target product milestone:** First real Warden Mission vertical slice using Gemini Computer Use / Playwright browser agency

---

## 0. Mission

Implement the **first real vertical slice of the Warden Mission-Control redesign**.

Do not attempt to redesign every Warden screen at once.

The goal of this milestone is to prove the new product model using a real capability that already exists in the runtime:

> **A user tells Warden what they want. Warden creates/continues a Mission. Gemini Computer Use performs real browser work. The Warden UI shows meaningful live work, exposes the browser context on demand, pauses when the operator is actually needed, resumes after a real approval decision, and finishes with evidence/proof.**

This milestone should make the new GUI architecture real without rewriting the working Warden runtime or destabilizing unrelated Build/provider functionality.

The end state should make Warden feel like an **operating console for outcomes**, not a collection of internal subsystems and provider tabs.

---

## 1. Source of truth and required reading

Before editing code, read these files in this order:

1. `AGENTS.md`
2. `docs/architecture/warden-gui-mission-control-redesign.md`
   - If this file is not yet on `master`, read it from PR #58 / branch `docs/gui-mission-control-redesign`.
3. `docs/architecture/warden-agent-runtime.md`
4. `desktop/architecture.md`
5. `src/warden/computer/service.py`
6. `src/warden/computer/models.py`
7. `src/warden/computer/confirmations.py`
8. `src/warden/agent_runtime.py`
9. `tests/test_warden_computer_use.py`
10. Current desktop renderer and tests listed below.

The GUI ADR defines the target product model. This handoff narrows that architecture into the **first executable implementation slice**.

If this handoff conflicts with `AGENTS.md`, follow `AGENTS.md`.

If implementation reveals that the ADR is wrong or incomplete, do not silently drift. Document the decision and update the ADR/handoff with the reason.

---

## 2. Repository state protocol

Before doing any work, prove repository state:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git fetch origin
git rev-parse origin/master
```

Expected baseline at handoff authoring:

```text
origin/master = edb2ef8bc5ae26fa5e9d3693c745554de1f0908f
```

Do not assume that SHA is still latest when executing this handoff. Always branch from current `origin/master` after the GUI ADR has been merged or otherwise made available in the implementation branch.

Create the implementation branch:

```bash
git switch master
git pull --ff-only origin master
git switch -c feat/mission-control-browser-vertical-slice
```

Do not rewrite shared history. Do not reset unrelated work. Do not work directly on `master`.

---

## 3. Why this is the first redesign milestone

Warden 0.6.2 now has a real Gemini Computer Use / Playwright subsystem that can:

- visually observe a browser through screenshots;
- navigate;
- click / double-click / right-click by pixel coordinate;
- type text;
- press keys / hotkeys;
- scroll;
- wait;
- collect browser observations;
- synthesize structured evidence;
- emit semantic Computer Use lifecycle events;
- identify high-impact actions that require confirmation.

That capability is ideal for the first redesign slice because it forces the GUI to solve several foundational product concepts at once:

1. Warden as the single front door.
2. Mission as the durable container for work.
3. A typed **Browser Work** card.
4. Real provider identity shown only when relevant.
5. A contextual right-side work surface.
6. Live observations/screenshots.
7. A real **Needs You** state.
8. Approval / denial / resume semantics.
9. Completion evidence and proof.
10. No requirement for the user to operate a terminal or browser manually.

Once these primitives exist for Computer Use, the same Mission architecture can absorb Build, Codex, Finish, Research, tests, diffs, preview, and other Warden capabilities.

---

## 4. Product principle

The default user should experience:

```text
Ask Warden
    ↓
Mission begins
    ↓
Meaningful work appears
    ↓
Open work only if desired
    ↓
Warden interrupts only when operator judgment is required
    ↓
Work resumes
    ↓
Result + proof
```

The default user should **not** need to understand:

- Captain internals;
- MCP/A2A;
- Warden tool registry mechanics;
- Computer Use function declarations;
- Playwright internals;
- raw runner/event IDs;
- browser screenshot storage paths;
- provider API architecture;
- worktree mechanics;
- terminal commands for this browser slice.

Those remain implementation details or advanced surfaces.

---

## 5. Critical runtime finding: confirmation is classified but not currently enforced

Treat this as a required correctness issue, not optional polish.

Current Computer Use behavior in `src/warden/computer/service.py` is effectively:

```text
plan action
    ↓
check_confirmation_required(action)
    ↓
if true: emit computer_confirmation_required
    ↓
continue loop
    ↓
execute_action(action)
```

That means the subsystem can identify a sensitive action and emit a confirmation event, but the service does not currently provide a true operator decision boundary before executing the action.

The current tests verify the classifier, but do not prove that a destructive/high-impact action is prevented from running without approval.

### Required invariant

After this milestone:

> **If an action requires confirmation, that action MUST NOT execute until an explicit operator approval is recorded.**

Deny must prevent execution.

No UI-only fake confirmation is acceptable.

### Sensitive examples already classified

The existing policy includes terms such as:

- delete
- destroy
- remove
- purge
- truncate
- buy
- purchase
- order
- pay
- checkout
- terminate
- shutdown
- wipe
- drop
- sign out
- log out
- revoke
- transfer

Do not weaken the existing classifier to simplify implementation.

---

## 6. Required runtime interaction model

Design and implement a real suspend / decision / resume seam.

Exact implementation mechanics are open to architecture review, but the behavior must be equivalent to:

```text
ComputerUseService session
        │
        ├── safe action
        │      ↓
        │   execute
        │
        └── confirmation-required action
               ↓
           persist pending action / confirmation request
               ↓
           session status = needs_user / awaiting_confirmation
               ↓
           emit confirmation event
               ↓
           STOP before action execution
               ↓
      Warden Mission → Needs You
               ↓
        operator decision
          /          \
      approve        deny
        ↓              ↓
    resume          do not execute
        ↓              ↓
 execute action    session resolves safely
```

### Requirements

- The pending action must be identifiable without exposing credentials/private values.
- Approval must apply to the specific pending request/action, not globally to all future sensitive actions.
- A deny decision must not execute the action.
- A stale/replayed approval must not accidentally approve a different pending action.
- Session state presented by the GUI must be derived from real runtime state.
- If restart/resume is implemented in this slice, stale pending execution must fail safe. If persistence is not implemented yet, document that limitation explicitly.
- Do not bypass or auto-approve confirmation in demo fixtures.

### Do not overbuild

Do not invent a giant general workflow engine solely to solve this slice.

Prefer the smallest clean contract that can later generalize to Git apply, publishing, account changes, and other consequential Warden actions.

---

## 7. Critical integration finding: live Computer Use events are not yet reaching the primary Warden UI as a stream

`ComputerUseService.run()` already supports an `event_callback` and emits useful events such as:

```text
computer_session_started
computer_action
computer_confirmation_required
computer_observation
computer_session_completed
```

The runtime wrapper currently invokes the service without providing that callback, and the main Warden runtime primarily exposes the final Computer Use completion/failure rich event after the tool returns.

This milestone must close that seam.

### Required outcome

The Electron Mission UI must be capable of receiving authoritative Computer Use progress while the session is actually executing.

The user should not have to wait for the entire tool call to return before seeing that browser work exists.

---

## 8. Normalize runtime activity into Mission events

Do not wire every raw backend event directly into one-off DOM logic.

Introduce or formalize a normalized Mission presentation/event contract.

Names may differ, but the conceptual model should support:

```ts
interface Mission {
  id: string
  projectId?: string
  objective: string
  status:
    | "planning"
    | "working"
    | "needs_user"
    | "verifying"
    | "ready"
    | "completed"
    | "failed"

  workItems: MissionWorkItem[]
  needsUser: NeedsUserItem[]
  evidence: MissionEvidence[]
}
```

And typed work:

```ts
type MissionWorkKind =
  | "research"
  | "browser"
  | "build"
  | "terminal"
  | "test"
  | "review"
  | "proof"
```

For this milestone, **browser** is required. The other kinds should be represented cleanly enough that future slices can add them without rewriting the Mission model.

### Computer Use mapping

At minimum:

```text
computer_session_started
  → create/update Browser Work item
  → Mission status = working

computer_action
  → update Browser Work summary/activity

computer_observation
  → attach/update observation metadata
  → update contextual work surface

computer_confirmation_required
  → Mission status = needs_user
  → create Needs You item
  → execution must actually be paused

approval recorded
  → clear/resolve Needs You item
  → Mission returns to working
  → session resumes

denial recorded
  → resolve Needs You item
  → action does not execute
  → Mission reflects truthful resulting state

computer_session_completed(status=completed)
  → Browser Work = complete
  → attach evidence
  → Mission continues or completes based on actual workflow

computer_session_completed(status=failed)
  → Browser Work = failed
  → Mission exposes failure truthfully
```

### Truth requirement

Do not create fictional agent messages to simulate activity.

Every visible active state must derive from real runtime/task/session state.

---

## 9. Target GUI for this slice

Do not attempt the full final GUI immediately. Implement the minimum shell that proves the architecture.

### Primary layout

Target three conceptual regions:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ WARDEN     [Project ▾]                   ● Working      Needs You 1    │
├───────────────────┬──────────────────────────────┬─────────────────────┤
│ LEFT RAIL         │ MISSION                      │ WORK SURFACE        │
│                   │                              │                     │
│ Warden / Home     │ conversation                 │ Browser             │
│ Needs You         │                              │ Activity            │
│                   │ typed work cards             │ Proof               │
│ Projects          │                              │                     │
│ Recent Missions   │                              │ screenshot/result   │
│                   │                              │                     │
│ Connected AI      │                              │                     │
│ Advanced          │                              │                     │
├───────────────────┴──────────────────────────────┴─────────────────────┤
│ Tell Warden what you want done…                               [Send]   │
└─────────────────────────────────────────────────────────────────────────┘
```

### This slice requires

#### Left rail

- Warden/Home entry.
- Needs You with real count.
- Active project identity.
- Recent Mission(s), at least enough to orient the user.
- Connected AI section may be minimal/read-only for this slice.
- Advanced/legacy access for old surfaces during migration.

Do **not** fully implement multi-account management yet unless it is necessary for the slice.

#### Mission center

- Warden conversation remains the main interaction surface.
- Browser Work card appears from real Computer Use execution.
- Card shows meaningful human-facing state, e.g.:
  - `Starting browser`
  - `Navigating`
  - `Inspecting page`
  - `Waiting for you`
  - `Completed`
  - `Failed`
- Provider/model metadata may appear secondarily, for example `Gemini Computer Use`, but the card is about the work, not provider branding.
- No raw internal IDs in default user-facing text.

#### Work surface

For this milestone, implement contextual views for:

1. **Browser**
2. **Activity**
3. **Proof**

The work surface must be openable/closable without leaving the Mission mental model.

Browser should show the latest real observation/screenshot when available.

Activity should show concise meaningful actions, not every low-level internal field.

Proof should show authoritative completion evidence from the session.

### Expanded behavior

The right work surface should be designed so it can later host:

- Research
- Terminal
- Preview
- Files
- Diff
- Tests
- Review
- Proof

Do not hardcode the panel architecture around browser-only assumptions.

---

## 10. Browser Work card behavior

Example working card:

```text
BROWSER WORK
Gemini Computer Use

Inspecting the target page
7 actions

[Open work]
```

Example Needs You state:

```text
NEEDS YOUR APPROVAL
Browser action

Warden is ready to click:
"Delete test project"

Reason: destructive action

[Allow once]  [Deny]  [Inspect]
```

Example completion card:

```text
BROWSER WORK COMPLETE

12 actions
Target: example.com
Result: Requested information found

Verified by session evidence

[See result]  [Proof]
```

Exact copy can improve during implementation, but hierarchy and truthfulness matter more than wording.

---

## 11. Needs You behavior

`Needs You` is not a decorative notification center.

It is the Warden-wide representation of work that cannot correctly proceed without operator judgment.

For this slice it must be backed by the real Computer Use confirmation gate.

### Requirements

When the session hits a confirmation boundary:

- global Needs You count increments;
- Mission status changes to `needs_user`;
- Browser Work card visibly waits;
- a specific Needs You item is available;
- Allow once resumes the exact pending action;
- Deny prevents execution;
- resolving the request decrements/removes the item;
- stale UI state must reconcile with backend truth.

The UI must never say `Waiting for approval` while the action is secretly continuing in the background.

---

## 12. Screenshots and browser observations

The Computer Use subsystem already stores screenshots and returns observation data.

Use real captured observations.

Do not introduce fake screenshots or hardcoded demo frames.

### UI requirements

- Show latest observation when Browser work is selected.
- Clearly indicate if no screenshot is available.
- Do not expose unsafe local filesystem paths in normal user-facing UI.
- Preserve evidence references internally as needed.
- Avoid re-encoding massive screenshot payloads repeatedly if a lighter local path/reference flow is available.
- Handle missing/deleted screenshot evidence gracefully.

### Privacy

Browser screenshots may contain sensitive information.

Do not log them unnecessarily. Do not send them to unrelated providers. Do not expose local evidence paths to embedded untrusted web content.

Follow existing Electron/webview/browser sandbox boundaries from `AGENTS.md` and `desktop/architecture.md`.

---

## 13. Provider identity

The UI should show **who actually performed work**, when known, without teaching the user a permanent fictional team model.

Good:

```text
Browser Work
Gemini Computer Use
Working
```

Bad:

```text
Spark Research says: I have begun researching!
Claude UX says: Waiting!
Codex Builder says: Standing by!
```

If no real task/session exists, no provider should be shown as working.

Do not hardcode Claude/Codex/Spark as active participants merely for visual richness.

---

## 14. Do not create a new top-level Computer Use workspace

Computer Use is a **Mission capability**.

Do not add sidebar items such as:

- Computer Use
- Gemini Browser
- Browser Agent
- Visual Agent

as a new peer to Warden/Build/Web Platforms.

The work belongs inside the Mission.

The browser context appears in the right work surface only when relevant or explicitly opened.

---

## 15. Preserve legacy capabilities during migration

Do not remove working functionality merely because the new shell exists.

During this milestone it is acceptable for old/legacy surfaces to remain reachable from an Advanced/legacy route.

Preserve unless directly required to change:

- current Build execution logic;
- Git-safe apply/undo semantics;
- official provider auth;
- persistent web platform profiles;
- OAuth sandbox behavior;
- Brain/runtime services;
- existing finish/evidence behavior;
- direct provider web access;
- terminal capability.

This milestone is a **vertical slice**, not the final deletion of old shells.

---

## 16. Primary files to inspect

### Runtime / Computer Use

```text
src/warden/agent_runtime.py
src/warden/computer/models.py
src/warden/computer/service.py
src/warden/computer/confirmations.py
src/warden/computer/screenshots.py
src/warden/computer/providers/base.py
src/warden/computer/providers/gemini_vertex.py
src/warden/computer/executors/base.py
src/warden/computer/executors/playwright_executor.py
```

### Existing API / streaming / group chat

Inspect existing Warden chat/API/SSE paths before inventing another transport. Reuse a working event path if it cleanly supports Mission events.

Search for:

```text
ChatEvent
SSE
stream
group chat
event_callback
rich_events
computer_session
```

### Desktop renderer

```text
desktop/src/renderer/index.html
desktop/src/renderer/index.ts
desktop/src/renderer/styles.css
desktop/src/renderer/simple-build.ts
desktop/src/renderer/copy.ts
```

### Desktop main/preload/shared

Inspect relevant seams rather than blindly editing all files:

```text
desktop/src/main/index.ts
desktop/src/main/platform-manager.ts
desktop/src/main/provider-auth.ts
desktop/src/main/evidence.ts
desktop/src/main/context-assembler.ts
desktop/src/preload/
desktop/src/shared/
```

### Existing tests

```text
tests/test_warden_computer_use.py
tests/test_ai_desk_functionality_repair.py
tests/test_group_chat.py
tests/test_group_chat_api.py

desktop/tests/renderer-chrome.test.ts
desktop/tests/state-store.test.ts
desktop/tests/run-store.test.ts
desktop/tests/evidence.test.ts
desktop/tests/context-handoff.test.ts
desktop/tests/simple-build.test.ts
desktop/tests/provider-auth.test.ts
desktop/tests/oauth-popup.test.ts
desktop/tests/providers.test.ts
desktop/tests/codex-events.test.ts
desktop/tests/git-safe-loop.test.ts
```

Also inspect existing browser/Electron Playwright tests under `tests/` before defining new selectors.

---

## 17. Files/systems not to casually rewrite

Do not replace these systems unless a demonstrated blocker requires a scoped change:

- `WardenAgentRuntime` core model/tool loop;
- Brain storage architecture;
- Captain persistence;
- Git-safe worktree/apply subsystem;
- official provider authentication;
- browser profile sandbox model;
- existing Finish pipeline;
- unrelated MCP/A2A interop;
- unrelated Warden Brain graph/UI;
- build provider implementations unrelated to the Mission adapter.

Do not rename broad public/internal APIs simply to make the new renderer aesthetically cleaner.

Prefer adapters over destructive rewrites.

---

## 18. Suggested implementation sequence

### Step A — architecture/state inventory

Before code changes, document:

- where Computer Use execution starts;
- where lifecycle events can be surfaced in real time;
- existing event transport that should be reused;
- how pending confirmation state will be represented;
- how operator decision reaches the suspended session;
- how Mission state will be derived;
- how screenshot evidence reaches the Electron renderer;
- where Mission state lives during this slice;
- what state survives restart and what does not.

Do not spend days on design documents. Produce the minimal contract needed to implement correctly.

### Step B — confirmation correctness

Implement and test the true approval boundary.

Required test first or alongside implementation:

> a confirmation-required mock action must not reach the executor before approval.

Also test denial.

### Step C — live event bridge

Connect real Computer Use lifecycle events to the UI-facing event transport.

Do not wait until tool completion to create the Browser Work card.

### Step D — Mission presentation model

Implement normalized state/adapters with deterministic unit tests.

Keep raw runtime objects out of direct DOM rendering where practical.

### Step E — first Mission shell

Implement the visible shell and center Mission flow.

Keep compatibility access to old surfaces.

### Step F — Browser contextual work surface

Render latest observation/screenshot, activity, and proof.

### Step G — Needs You UI

Connect real approval/deny buttons to the actual suspended session.

### Step H — packaged Electron proof

Run the real installed/packaged app and complete both acceptance scenarios below.

---

## 19. Agent ownership / parallelization

Do not have multiple agents simultaneously rewrite the same renderer files.

### Agy — architecture/runtime seam owner

Primary responsibility:

- inspect current event transport;
- design/implement the smallest correct Computer Use pause/resume contract;
- design/implement the live Mission event bridge;
- define normalized Mission event/state interface if backend contract is required;
- add runtime-focused tests;
- produce a concise handoff to the renderer implementer.

Agy must answer concretely:

1. How does `computer_action` reach the Electron Mission UI while execution is live?
2. What exact state represents a pending confirmation?
3. What exact API/event resolves approval/denial?
4. How is a stale approval prevented from authorizing another action?
5. What state is authoritative after restart?

Do not accept vague answers such as "the frontend can listen for it."

### Codex — renderer/vertical-slice implementation owner

Primary responsibility after runtime contract is stable:

- Mission presentation model/adapters;
- new primary shell for the slice;
- Browser Work card;
- right contextual work surface;
- Needs You UI;
- proof rendering;
- desktop unit tests;
- Electron/Playwright verification.

Codex should reuse existing runtime execution; it should not create a competing Computer Use implementation.

### Jules — independent reviewer / verifier

Jules should review rather than invent another GUI implementation.

Verify:

- runtime truth;
- confirmation really blocks execution;
- denial really prevents execution;
- no fake active agents;
- no hardcoded demo-only state;
- compact window behavior;
- old Build/provider access still works;
- screenshot/context surface behavior;
- state reconciliation;
- packaged Electron behavior;
- tests actually cover the claimed invariants.

Jules should provide fixes only where isolated and clearly scoped, or return findings to Codex/Agy.

### Parallel file ownership

A safe default split:

```text
Agy:
  src/warden/computer/*
  runtime/API event bridge
  Python tests

Codex:
  desktop/src/renderer/*
  desktop presentation adapters
  desktop tests

Jules:
  review + new independent tests / smoke harness where possible
```

If Agy and Codex must both touch a shared API/preload file, agree on the contract first.

---

## 20. Acceptance Scenario A — safe browser mission

The first required installed-build scenario is intentionally simple.

### User objective

```text
Go to example.com, inspect the page, and tell me what it says.
```

### Required visible flow

1. Warden is the default front door.
2. User submits the objective without selecting a provider or Build workspace.
3. A real Mission is created/continued.
4. A Browser Work card appears while Computer Use is actually running.
5. Provider identity is truthful (`Gemini Computer Use` or the actual provider used).
6. Opening work reveals the Browser contextual surface.
7. A real screenshot/observation appears.
8. Real meaningful browser activity updates as execution proceeds.
9. User manually types no browser automation or terminal commands.
10. Computer Use completes.
11. Warden synthesizes the answer naturally.
12. Browser Work transitions to complete.
13. Proof/evidence is inspectable.
14. No fake agents are shown as working.

### Failure criteria

The scenario fails if:

- Browser Work appears only after the tool call is already complete;
- screenshots are fake/demo fixtures in the packaged flow;
- the UI exposes raw internal IDs as primary content;
- Warden requires the user to navigate to a new Computer Use workspace;
- the user must manually use the browser or terminal;
- work state is hardcoded rather than driven by the runtime.

---

## 21. Acceptance Scenario B — real Needs You gate

Use a controlled local fixture/test application. Do not perform destructive operations against real user data or real paid services merely to prove the feature.

### User objective

Equivalent to:

```text
Open the local test app and delete the test project.
```

### Required behavior

1. Browser mission starts normally.
2. Computer Use reaches the sensitive action.
3. Confirmation policy identifies the action as requiring approval.
4. The action does **not** execute.
5. Session enters a real waiting/needs-user state.
6. Global Needs You becomes `1`.
7. Mission visibly indicates waiting for user.
8. Needs You item describes the pending action clearly.
9. `Allow once` approves only that pending action.
10. Execution resumes and the approved action can execute.
11. Needs You resolves.

Repeat with denial:

1. Reach the same/similar sensitive action.
2. Click `Deny`.
3. The action must not execute.
4. The session/Mission resolves truthfully rather than pretending success.

### Required automated tests

At minimum test:

```text
confirmation-required action does not call executor before approval
approved action executes exactly once
denied action never executes
stale/mismatched approval does not authorize a different pending action
Needs You derivation reflects pending confirmation truth
```

---

## 22. Acceptance tests — UI/model

Add deterministic tests for at least:

### Mission state

- no work → Ready/idle;
- active Computer Use → working;
- pending confirmation → needs_user;
- completed session → completed or next truthful Mission state;
- failed session → failed/attention state;
- no fictional provider status when idle.

### Browser Work card

- created from start event;
- updates from action/observation events;
- exposes correct provider metadata;
- opens Browser work surface;
- completion/failure state is truthful.

### Needs You

- count derives from real unresolved decision items;
- approval resolves the correct item;
- denial resolves the correct item;
- resolved item does not remain in count.

### Contextual surface

- opens/closes cleanly;
- Browser/Activity/Proof routes render appropriate content;
- missing screenshot/evidence states are safe and understandable;
- compact layout remains usable.

---

## 23. Existing regression gates

Run focused tests while working, then full gates before completion.

### Computer Use

```bash
PYTHONPATH="$PWD:$PWD/src" .venv/bin/python -m pytest \
  tests/test_warden_computer_use.py -v
```

Add new focused tests for pause/approve/deny semantics.

### Relevant Warden runtime/chat tests

```bash
PYTHONPATH="$PWD:$PWD/src" .venv/bin/python -m pytest \
  tests/test_ai_desk_functionality_repair.py \
  tests/test_group_chat.py \
  tests/test_group_chat_api.py -q
```

Adjust exact file set only if paths have changed; do not silently skip equivalent coverage.

### Desktop

```bash
cd desktop
npm ci
npm run check
```

The previous Computer Use merge reported 80 desktop tests across 16 files; exact counts may legitimately change. Report actual current counts, never expected/hardcoded counts.

### Python broad regression

For Python-affecting changes, follow `AGENTS.md`:

```bash
PYTHONPATH="$PWD:$PWD/src" .venv/bin/python -m pytest \
  tests --ignore=tests/e2e --ignore=tests/browser -q
```

### Public release audit

```bash
bash scripts/public_release_audit.sh
```

### Visible GUI proof

Visible UI changes require a real installed/packaged Electron smoke under the normal Chromium sandbox.

Do not claim UI completion from static HTML/unit tests alone.

---

## 24. Visual quality bar

The first slice does not need every final design feature, but it must look intentional enough to become the foundation rather than disposable prototype UI.

### Required qualities

- clear hierarchy;
- Warden is visually primary;
- Mission title/objective is obvious;
- work status can be understood at a glance;
- provider identity is secondary to outcome;
- Needs You is impossible to miss when active but not noisy when empty;
- right work surface feels contextual, not like another whole app embedded inside the app;
- activity is compressed and readable;
- no wall of raw events;
- no permanent "four-agent team" chrome;
- no fake loading/working animation detached from authoritative state;
- useful at normal desktop and compact window widths.

### Avoid

- neon/glow-heavy "AI dashboard" aesthetics solely for effect;
- giant metrics dashboards unrelated to the user's objective;
- excessive badges;
- emoji as core navigation semantics;
- provider logos dominating the Mission;
- dense developer terminology in default mode;
- another nested sidebar inside the contextual work surface.

---

## 25. Product copy guidance

Prefer human language.

Use:

- `Working`
- `Waiting for you`
- `Checking result`
- `Completed`
- `Couldn't complete`
- `Open work`
- `Proof`
- `Allow once`
- `Deny`

Avoid making default UI depend on terms like:

- orchestrator
- MCP
- A2A
- event callback
- runner ledger
- context revision
- worktree
- function declaration

Power-user/Advanced views can retain technical detail.

---

## 26. Error handling requirements

Handle at least:

- provider unavailable;
- Computer Use model/provider error;
- browser launch failure;
- screenshot capture failure;
- maximum step limit reached;
- stale confirmation request;
- approval API failure;
- denial flow;
- UI reconnect while mission is active;
- session completed while UI was disconnected;
- evidence path missing;
- runtime event parsing/version mismatch.

Errors must be truthful and actionable.

Do not leave the UI stuck at `Working` after backend failure.

---

## 27. State/restart expectations

For this slice, explicitly document what is durable.

At minimum:

- completed Mission history should not become fake live work after restart;
- dead Computer Use processes must not be shown as active merely because old UI state restored;
- unresolved confirmations must fail safe if they cannot be reliably restored;
- Needs You count must reconcile against authoritative state rather than blindly restoring a cached number.

If live Computer Use resume across full app restart is not part of this milestone, state that clearly. Do not simulate resume.

---

## 28. Security and isolation

Preserve all existing boundaries.

Especially:

- remote websites remain sandboxed;
- no Node integration in untrusted remote content;
- browser websites cannot access privileged Warden IPC/filesystem/terminal/Brain surfaces;
- do not expose provider credentials;
- do not commit screenshots containing user secrets;
- do not commit browser profiles or local session data;
- website auth remains separate from official local Build/client auth;
- do not silently switch subscription workflows to API billing;
- public release audit must remain clean.

---

## 29. Non-goals for this milestone

Do **not** expand scope into all of the following:

- complete Connected AI multi-account manager;
- final multi-account OAuth redesign;
- full Build-to-Mission migration;
- deletion of all legacy Warden web UI;
- total rewrite of `desktop/src/renderer/index.ts` solely for framework preference;
- React migration;
- full Agent Bench;
- new plugin marketplace;
- full desktop OS agency beyond what is required for Browser v0.1;
- full mobile UI;
- redesign of Brain Graph;
- redesign of every Settings screen;
- new MCP/A2A protocol work unrelated to this slice.

Do not turn a focused vertical slice into a six-week platform rewrite.

---

## 30. Definition of done

This milestone is done only when all of the following are true:

### Runtime correctness

- Computer Use confirmation-required actions cannot execute before explicit approval.
- Denial prevents the action.
- Live Computer Use lifecycle can reach the UI while execution is happening.
- Mission state is derived from authoritative execution state.

### GUI

- Warden is the default front door.
- A Browser Work card appears during real execution.
- Browser/Activity/Proof contextual views work.
- Needs You reflects a real suspended action.
- Approval/deny controls operate the actual backend decision.
- No fake agent work is displayed.

### Verification

- focused Python tests pass;
- relevant runtime/chat tests pass;
- broad Python regression passes if Python was changed;
- `cd desktop && npm run check` passes;
- public release audit passes;
- packaged/installed Electron smoke passes;
- Scenario A passes end-to-end;
- Scenario B approval path passes end-to-end;
- Scenario B denial path passes end-to-end.

### Git

- implementation is on a feature branch;
- branch is clean after commit;
- no unrelated changes included;
- PR opened against `master`;
- PR description includes verification proof;
- merge only after review/verification.

---

## 31. Commit guidance

Use scoped commits. A reasonable structure is:

```text
feat(computer-use): enforce operator confirmation pause and resume
feat(missions): bridge live computer-use events into mission state
feat(desktop): add mission browser work and needs-you surfaces
test(missions): prove browser work and approval state transitions
```

If one cohesive squashed commit is preferred at PR merge, suggested final commit title:

```text
feat(ai-desk): add Mission browser work and real Needs You approval loop
```

Do not use vague commit messages such as `update ui` or `fix stuff`.

---

## 32. Required final agent report

Return a structured report with these exact sections.

### Proven

Include:

- starting `master` SHA;
- feature branch;
- final feature SHA(s);
- exact files changed;
- exact runtime contract implemented;
- exact confirmation behavior proven;
- exact tests run and results;
- packaged Electron path/version if built;
- screenshots/video/browser proof captured;
- Scenario A result;
- Scenario B approve result;
- Scenario B deny result;
- final Git status.

### Claimed but not proven

List anything believed true but not directly verified.

Do not leave this section out if there are unverified assumptions.

### Regressions / unresolved issues

List all known failures, degraded behavior, skipped checks, or deferred concerns.

### Architecture changes vs ADR

State whether implementation followed the ADR exactly. If not, describe each deviation and why it was necessary.

### Next recommended slice

If this milestone is complete, the next likely target is:

> **Absorb existing Simple Build / structured provider execution into the same Mission + contextual work-surface model.**

Do not start that next slice inside this PR unless it is required to complete the Browser vertical slice.

### PR / merge status

Provide:

- PR number and URL;
- base/head SHAs;
- merge readiness;
- exact command or review action the operator should perform next.

---

## 33. Final instruction to the implementation agent

Build the smallest **real** version of the future Warden interface.

Do not optimize for a screenshot.

Do not create fake agents, fake browser activity, fake tests, fake proof, or a confirmation modal that does not actually stop the action.

Use the existing Computer Use subsystem, existing Warden runtime, existing provider/auth boundaries, and existing Electron application as the foundation.

The milestone succeeds when a person can tell Warden to perform a browser task, watch meaningful progress without understanding Playwright or Gemini internals, inspect the real browser work if they want, be interrupted only when a consequential decision truly requires them, make that decision, and receive a verified result.

That interaction is the foundation for the rest of the Warden GUI redesign.
