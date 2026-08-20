# Warden 0.6.1 Agent Runtime Architecture

**Document ID**: `ADR-20260820-WARDEN-AGENT-RUNTIME`  
**Status**: Active / Implemented  
**Scope**: Conversational front door, model-driven tool execution, truthful state reflection  

---

## 1. Context & Motivation

Manual dogfood of Warden AI Desk 0.6.0-rc.1 identified that the "Talk to Warden" surface was behaving like a deterministic command/intent router rather than a genuine AI agent. When asked open-ended questions like *"tell me what i was doing yesterday"*, Warden returned a static capability menu. When asked *"what have I been browsing tonight?"*, raw internal `browser-*` record IDs were dumped directly to the user. Furthermore, the desktop header displayed a static `● 3 working` badge regardless of actual execution state.

Warden 0.6.1 formalizes **`WardenAgentRuntime`** as the persistent, model-driven, tool-using intelligence layer of Warden. Brain, Captain, Tasks, Control Plane, Git, and Finish are capabilities behind Warden — not substitutes for Warden.

---

## 2. Core Architecture

```text
  +-------------------------------------------------------------+
  |                   Talk to Warden / AI Desk                  |
  +-------------------------------------------------------------+
                                 │
                     (Human natural language)
                                 ▼
  +-------------------------------------------------------------+
  |              WardenAgentRuntime (src/warden)                |
  |  - Compact context assembly (Project, Git, Status, Brain)   |
  |  - Provider-neutral model inference                         |
  |  - Bounded tool execution loop (max_turns = 5)              |
  |  - Evidence synthesis (hiding raw IDs, deduplicating noise) |
  +-------------------------------------------------------------+
                                 │
                   Structured Tool Dispatch Seam
                                 │
     ┌─────────────┬─────────────┼─────────────┬─────────────┐
     ▼             ▼             ▼             ▼             ▼
+─────────+   +─────────+   +─────────+   +─────────+   +─────────+
|  Brain  |   | Activity|   | Captain |   |  Tasks  |   | Finish  |
| Recall/ |   | Search/ |   | Durable |   | & Runs  |   | Pipeline|
|Remember |   | Browser |   |  Plans  |   | State   |   | & Verify|
+─────────+   +─────────+   +─────────+   +─────────+   +─────────+
     │             │             │             │             │
     └─────────────┴─────────────┼─────────────┴─────────────┘
                                 ▼
  +-------------------------------------------------------------+
  |              Authoritative Evidence & Response              |
  |  - Rich Interactive Cards (plan_created, decision, finish)   |
  |  - Synthesized natural language Markdown                    |
  |  - Truthful Header Badge (Ready vs N working)               |
  +-------------------------------------------------------------+
```

---

## 3. Tool Registry Families

The runtime exposes a structured JSON-schema tool registry (`WardenToolRegistry`):

1. **`brain_recall(query, limit)`**: Queries Brain for past architectural decisions, constraints, and verification proofs.
2. **`brain_remember(content, kind, title)`**: Persists permanent operator preferences, constraints, or decisions directly to `_mctable/workbench/memories/` without requiring slash commands.
3. **`activity_search(query, limit)`**: Retrieves recent browser and workbench activity, automatically grouping visits, filtering authentication/flow redirects, and hiding raw internal IDs (`browser-*`) from user-facing text.
4. **`project_inspect(repo_path)`**: Inspects current git branch, commit log, and working tree modification status.
5. **`captain_plan(goal, steps)`**: Formulates and persists a genuine multi-step plan to `_mctable/captain/plans.json` via `persist_plan()`, emitting interactive `plan_created` cards with all initial steps `queued`.
6. **`tasks_inspect(status)`**: Inspects authoritative board tasks in `_mctable/tasks/assigned/`.
7. **`runs_inspect()`**: Queries actual active runner sessions (reflecting true execution state).
8. **`finish_project(objective)`**: Invokes the persistent 9-point verification pipeline to build, test, provision preview, and prepare for production release.

---

## 4. Truth Invariants

1. **No Fake Agent Delegation**: Warden never emits simulated messages from Claude UX, Spark Research, or Codex Builder unless an actual task or runner is executing.
2. **Authoritative UI Indicators**: The `● Ready` / `● N working` header badge and participant pills are dynamically derived from active run states. If 0 runs are active, the UI indicates `Ready` / `Available`.
3. **Raw IDs Kept Internal**: Database and memory record identifiers (`browser-f7ccfc0f8d4a`, `m-decision-...`) are treated as internal evidence and omitted from user-facing summaries by default.
4. **Single-Boundary Control Plane**: Consequential operations (such as promoting to production) require explicit operator sign-off and cannot be bypassed.
5. **Fast-Path Slash Commands**: Power-user commands (`/status`, `/tasks`, `/runs`, `/proof`, `/finish`, `/stop`) remain available as deterministic shortcuts.
