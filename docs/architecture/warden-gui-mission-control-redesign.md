# Warden GUI Mission-Control Redesign

**Document ID:** `ADR-20260820-WARDEN-GUI-MISSION-CONTROL`  
**Status:** Proposed / Working source of truth  
**Date:** 2026-08-20  
**Audience:** Warden operator, Agy, Codex, Jules, Claude, and other implementation/review agents  
**Baseline:** Warden `master` at the 0.6.1 real-agent-runtime era (`927094c` at time of authoring)  
**Scope:** Desktop product information architecture, interaction model, mission UX, connected-AI UX, review/proof UX, and demo-readiness  
**Related architecture:** `docs/architecture/warden-agent-runtime.md`, `docs/architecture/context_economy.md`, `docs/architecture/warden_mcp2_interop.md`, `desktop/architecture.md`, `AGENTS.md`  

---

## 0. Executive decision

Warden should stop presenting its internal architecture as the product.

The desktop product must converge on **one primary operating surface** where the user tells Warden what they want, watches meaningful work happen, inspects the result when useful, and intervenes only when judgment or permission is actually required.

The target mental model is:

> **Warden is the primary UI. Projects organize the work. Missions contain the work. AI subscriptions/accounts are resources. Agents appear when they materially contribute. Proof establishes that work is actually done.**

The current top-level separation between **Talk to Warden**, **Web Platforms**, and **Build** is too architecture-aware for the product Warden is becoming. The capabilities behind those surfaces are valuable and should largely be preserved, but they should be recomposed around a single Mission experience.

The primary flow becomes:

```text
Ask Warden
    ↓
Warden understands the project and desired outcome
    ↓
Warden creates/continues a Mission
    ↓
Warden selects available capabilities/providers/accounts
    ↓
Research / build / browser / terminal / tests / review happen as needed
    ↓
The UI surfaces meaningful transitions, not raw tool chatter
    ↓
User is interrupted only for judgment, approval, or review
    ↓
Warden presents the result with proof
```

This is not merely a visual refresh. It is an information-architecture correction intended to make Warden understandable to a non-developer in seconds while remaining powerful enough for advanced operators.

---

## 1. Why this document exists

Warden now has substantial real capability:

- a model-driven `WardenAgentRuntime` rather than a keyword router;
- Brain recall and remember;
- recent activity search;
- Captain planning;
- task and runner inspection;
- project/Git inspection;
- persistent Finish/verification flows;
- structured build providers and local terminal access;
- persistent provider browser profiles;
- evidence and proof concepts;
- multi-agent and MCP/A2A infrastructure;
- isolated worktrees and an apply/review loop;
- a packaged Electron desktop application.

The 0.6.1 runtime architecture already establishes the correct runtime principle:

> Brain, Captain, Tasks, Control Plane, Git, and Finish are capabilities behind Warden — not substitutes for Warden.

The GUI must now honor the same principle.

Today, the interface still exposes many of those internal systems as separate destinations. That increases cognitive load, weakens the commercial story, and makes a product demo require explanation before the viewer can understand what Warden actually does.

This document defines the target experience and a migration path that intentionally **reuses the working runtime** rather than rewriting it.

---

## 2. Current-state diagnosis

### 2.1 Current Electron shell

At the time of this document, the desktop renderer exposes three peer workspaces:

1. **Talk to Warden** — described as Captain + Brain + Team.
2. **Web Platforms** — persistent provider web surfaces such as Claude/Gemini/Grok/custom platforms.
3. **Build** — local terminals and structured provider runs.

It also exposes individual platforms in the sidebar and advanced/provider controls.

The desktop shell embeds the Warden web UI for Team Chat through an iframe, while the Build surface is implemented directly in the Electron renderer.

### 2.2 Current embedded Warden taxonomy

The embedded Warden web interface currently exposes another broad navigation taxonomy including concepts such as:

- Team Chat
- Command Center
- Captain Desk
- Assistant
- Agent Library
- Tasks
- Proof
- Runner Sessions
- Brain
- Mail Accounts
- Memories
- Brain Inbox
- Brain Graph
- Model Gateway
- Settings

Team Chat also exposes named participants and a Team & Work drawer with Captain/team state, active tasks, approvals, memories, and proofs.

### 2.3 Why this is a problem

The problem is not primarily CSS or visual polish.

The problem is **architecture leakage**.

A new user sees internal categories before they understand the outcome-oriented product:

```text
Talk
Platforms
Build
Captain
Agent Library
Tasks
Proof
Brain
Memories
Runners
...
```

But the user generally arrives with an intent closer to:

```text
"Fix this."
"Research this and make a recommendation."
"Build this."
"Put this online."
"What were we doing yesterday?"
"Finish this and make sure it works."
```

Warden's UI should start with the user's desired outcome and reveal internal machinery only when it becomes useful.

### 2.4 Demo problem

A 30–60 second demo cannot spend time teaching viewers which Warden screen they are on.

The product should be self-explanatory enough that a viewer can see:

1. a user asks for an outcome;
2. Warden understands context;
3. Warden coordinates useful work;
4. real technical activity occurs;
5. the result appears;
6. Warden proves it worked.

If a narrator must explain the difference between Team Chat, Captain Desk, Build, and Web Platforms before the value is visible, the GUI is fighting the product.

---

## 3. Product thesis for the GUI

Warden is not primarily:

- an IDE;
- a terminal wrapper;
- a chatbot tab manager;
- Slack for AI agents;
- a Captain dashboard;
- a multi-agent visualization toy;
- a collection of embedded provider websites;
- an MCP inspector.

Warden is an **operating console for outcomes**.

The user should be able to think:

> "I tell Warden what I want. Warden remembers the project, uses the right AI/tools, does the technical work, asks me only when it needs my judgment, and proves the result."

The GUI must make that sentence visually true.

---

## 4. Core UX principles

### Principle 1 — Warden is the front door

The primary input is always natural-language intent to Warden.

The user should not need to decide whether a request belongs in Brain, Captain, Build, Codex, Gemini, a terminal, or a browser before work begins.

Those are execution details Warden can determine or expose progressively.

### Principle 2 — Missions are the durable unit of work

A Mission is the container for an outcome and everything required to achieve it:

```text
Mission
├── Conversation
├── Intent / objective
├── Plan
├── Research
├── Agent/provider work
├── Browser work
├── Terminal activity
├── Files / changes
├── Tests / checks
├── Approvals
├── Review
├── Proof
└── Result
```

A Mission may be tiny or large. A question that requires no durable execution can remain conversational, but once Warden is doing consequential or multi-step work it should become a Mission.

### Principle 3 — Work should render, not narrate

Do not make agents fill the conversation with status prose such as:

```text
Claude: I am starting work.
Spark: I am researching.
Codex: I am waiting.
Claude: I changed three files.
```

Instead use typed, inspectable work objects:

```text
[Research · Working]
[Plan · Ready]
[Build · 6 files changed]
[Verification · 148 tests passed]
[Approval · Needs you]
[Proof · Complete]
```

The conversation should contain judgment, synthesis, questions, and decisions. Execution telemetry belongs in compact work cards and drill-down surfaces.

### Principle 4 — Background work stays background

The system should not demand attention simply because activity exists.

The most important global question is:

> **Does Warden need me?**

That is more useful than a dashboard that says "three agents active."

### Principle 5 — Human state beats infrastructure state

Prefer states like:

- Draft
- Working
- Needs You
- Ready to Review
- Done
- Failed
- Paused

Avoid making the user reason about:

- runner process state;
- queue internals;
- worktree IDs;
- raw event IDs;
- MCP message types;
- provider RPC state;
- internal database identifiers.

Those details remain available in Advanced mode.

### Principle 6 — Proof is a first-class product surface

Warden should visually distinguish:

- **claimed** — an agent says something happened;
- **observed** — Warden captured supporting evidence;
- **verified** — an explicit check passed;
- **reviewed** — an independent review completed;
- **approved** — the operator accepted a consequential action.

"Done" must mean more than "the model stopped typing."

### Principle 7 — The terminal is visible proof, not a prerequisite

The terminal should not disappear from Warden.

For non-developers, it is powerful evidence that Warden is actually doing the work that other assistants tell them to do manually.

But the default interaction is:

> Warden operates the terminal; the user watches or inspects when useful.

not:

> Warden tells the user which commands to copy into a terminal.

### Principle 8 — Connected AIs are resources, not destinations

ChatGPT, Gemini, Claude, HyperAgent, Codex, Jules, etc. should be represented primarily as connected capabilities/accounts that Warden can use.

Direct provider access remains useful and should remain available, but it should be secondary to the Warden Mission flow.

### Principle 9 — Dynamic staffing, truthful identities

Do not hardcode an RPG party of permanent synthetic coworkers.

Warden should represent actual work performed by actual available providers/accounts/capabilities.

If Codex built something, show Codex. If Gemini performed research, show Gemini. If there is no real runner, do not imply that a named agent is working.

This matches the 0.6.1 runtime truth invariant: no fake agent delegation.

### Principle 10 — Progressive disclosure

Default mode should be understandable to a motivated non-developer.

Advanced users must still be able to inspect:

- terminal output;
- raw events;
- Git detail;
- files/diffs;
- runner sessions;
- provider identity;
- MCP/A2A information;
- proof artifacts;
- Brain internals where appropriate.

The solution is not removal. It is hierarchy.

---

## 5. Competitive design research and lessons

This section is not a requirement to clone another product. It records patterns that support Warden's target direction.

### 5.1 Cursor — agents as work, contextual work surfaces

Relevant patterns:

- agent-centric work rather than treating files as the only primary object;
- multiple parallel agent sessions;
- worktrees and isolation;
- browser/files/diffs/terminal as contextual surfaces;
- the main workspace can change depending on what needs attention rather than permanently giving chat all available space.

Warden lesson:

> Conversation can remain the coordinator while Preview, Diff, Terminal, Browser, Research, or Proof temporarily becomes the main object of attention.

Reference:

- https://cursor.com/changelog/3-0
- https://cursor.com/changelog/3-4

### 5.2 OpenAI Codex app — command center for agents

Relevant patterns:

- projects organize threads/work;
- agents can work independently;
- worktrees isolate changes;
- review and diffs belong with the work rather than in an unrelated product section;
- a desktop agent environment acts as a command center rather than only a chat screen.

Warden lesson:

> A Mission should contain its planning, execution, review, and evidence instead of bouncing the user between Talk and Build.

Reference:

- https://openai.com/index/introducing-the-codex-app/
- https://help.openai.com/en/articles/6825453-release-notes

### 5.3 Claude Code Desktop — adaptive workspace

Relevant patterns:

- parallel sessions;
- Git isolation;
- integrated terminal/editor/preview;
- visual diffs;
- side conversations and flexible work layout.

Warden lesson:

> Developer surfaces can exist inside a human-first application without becoming top-level mental models.

Reference:

- https://code.claude.com/docs/en/desktop

### 5.4 Replit — preview first, compressed agent telemetry, human task states

Relevant patterns:

- Preview is prominent for non-developer understanding;
- agent tool calls are compressed/grouped instead of flooding chat;
- file changes link directly to diffs;
- task boards use understandable states;
- checkpoints/history are presented as recoverable human-level milestones rather than raw Git mechanics.

Warden lesson:

> Show the result first, collapse low-value execution chatter, and translate infrastructure into human states.

References:

- https://docs.replit.com/updates/2025/04/18/changelog
- https://docs.replit.com/updates/2026/01/16/changelog
- https://docs.replit.com/references/agent/task-board
- https://docs.replit.com/learn/build-with-agent

### 5.5 Linear — attention queues and guided review

Relevant patterns:

- delegated work is shown as work with status rather than chatbot theater;
- assigned/delegated work can be collected into a focused queue;
- guided review can explain what changed and why before showing implementation detail.

Warden lesson:

> "Needs You" should be a core surface, and review should begin with a plain-English change summary before raw diff detail.

Reference:

- https://linear.app/changelog
- https://linear.app/changelog/2026-05-27-linear-diffs

### 5.6 Warp — terminal power behind agent workflows

Relevant patterns:

- multiple agent sessions;
- notifications when approval/review is required;
- review beside execution;
- terminal activity remains available as a real execution surface.

Warden lesson:

> Keep terminal truth and visibility without forcing terminal literacy.

Reference:

- https://www.warp.dev/agents

---

## 6. Target information architecture

### 6.1 Top-level product model

The default application should be organized around four concepts:

1. **Warden** — primary conversational/operational surface.
2. **Projects** — persistent context boundary and work organization.
3. **Missions** — durable outcomes and execution history.
4. **Needs You** — attention/review/approval queue.

Connected AI accounts should be present but secondary.

### 6.2 Recommended left rail

Conceptual target:

```text
WARDEN
● Home
  Needs You              2

PROJECTS
▾ Warden
   0.6.1 runtime
   GUI redesign          ●
   MCP v2
▸ GradeMy
▸ Marius

RECENT
Settings accounts
GUI redesign
Release verification

CONNECTED AI
ChatGPT · Personal       ●
Gemini · Personal        ●
Gemini · Startup         ●
HyperAgent · Primary     ●
HyperAgent · Research    ●
Claude                   ○ hidden/disabled

+ Add AI

Settings
Advanced controls
```

The exact labels can evolve, but the hierarchy should remain stable:

- orientation first;
- work second;
- resources third;
- internals last.

### 6.3 Recommended top bar

The top bar should answer system-wide context questions without becoming a dashboard.

Example:

```text
Warden                  Warden project ▾        2 working       Needs You 1
```

Useful elements:

- product identity;
- active project selector;
- truthful current work count;
- Needs You indicator;
- optional global search/command trigger;
- profile/settings affordance.

Avoid permanent fake participant counts.

---

## 7. Primary Warden surface

### 7.1 Purpose

The center surface is where the operator communicates intent and where Warden communicates decisions, synthesis, questions, and meaningful execution transitions.

### 7.2 Conversation rules

Conversation messages should be reserved for:

- user intent;
- Warden's interpretation;
- clarifications that are genuinely required;
- decisions/recommendations;
- summaries;
- consequential questions;
- completion/result synthesis.

Do not use conversational bubbles for every tool invocation.

### 7.3 Work cards

Execution appears as typed cards in the Mission stream.

Minimum card types:

- `plan`
- `research`
- `build`
- `browser`
- `terminal`
- `changeset`
- `test`
- `review`
- `approval`
- `proof`
- `failure`
- `checkpoint`

Each card should answer five questions at a glance:

1. What kind of work is this?
2. Who/what is actually doing it?
3. What is the status?
4. What meaningful result exists so far?
5. Can I inspect it?

Example:

```text
RESEARCH                                         Complete
Gemini · Startup account

Compared 3 approaches for persistent Google multi-account sessions.
Recommendation: isolate browser profile/account state by named Warden account.

12 sources · 3 approaches · 1 recommendation
[Open research]
```

Example:

```text
BUILD                                            Working
Codex

Implementing account switching in Settings.
6 files touched · verification next

[Open work]
```

Example:

```text
VERIFICATION                                     Passed
Warden

148 tests passed
Electron launched
Restart persistence passed
No unrelated files changed

[Proof]
```

### 7.4 Composer

The default composer should be broad and outcome-oriented:

> **Tell Warden what you want done…**

or

> **Ask Warden anything or tell it what you want done…**

The current 0.6.1 copy is directionally correct.

Optional secondary controls may include:

- attach file/context;
- choose/confirm project;
- add acceptance criteria;
- change execution policy;

But these should not turn the composer into a Jira form.

### 7.5 Mission creation behavior

Warden may create a Mission when one or more of these are true:

- the user asks for a multi-step outcome;
- external tools will be invoked;
- files may change;
- a browser/terminal action is needed;
- work may continue asynchronously within the app session;
- review/approval/proof is useful;
- there is value in durable history.

Simple questions can remain conversation-only.

---

## 8. Contextual work surface

### 8.1 Purpose

The right/context surface answers:

> **Show me the actual work.**

It replaces the need for Build to be a separate top-level product destination.

### 8.2 Supported views

The context surface should be able to render:

- Plan
- Research
- Preview
- Browser
- Terminal
- Files
- Diff
- Tests
- Proof
- Memory/context
- Agent/provider details
- Raw events in Advanced mode

### 8.3 Layout behavior

Default state:

- center Mission surface occupies primary width;
- context panel closed or compact.

When the user opens a work card:

- context panel opens at roughly 35–50% width;
- Mission conversation remains visible.

For content that deserves focus:

- Preview, Diff, Browser, Terminal, or Research may expand to majority width;
- conversation can compress to a narrow rail/floating composer;
- the user can return to the previous layout without losing Mission state.

### 8.4 No navigation penalty

Opening Terminal, Diff, or Preview should not switch the user into a conceptually separate application mode.

The user's location remains:

```text
Project → Mission → selected work object
```

not:

```text
Talk → Build → terminal tab → back → Proof → Team Chat
```

---

## 9. Mission state model

### 9.1 Human-level states

Recommended canonical Mission states:

```text
DRAFT
WORKING
NEEDS_YOU
READY
DONE
FAILED
PAUSED
CANCELLED
```

Optional sub-state/detail can remain richer internally.

### 9.2 State definitions

#### DRAFT

Warden has captured the objective but execution has not started.

#### WORKING

One or more real work units are active.

#### NEEDS_YOU

Progress is blocked on operator judgment, permission, choice, or required review.

#### READY

Execution is complete enough for operator review but has not reached the Mission's accepted completion state.

#### DONE

The defined result has been achieved and required verification/approval conditions are satisfied.

#### FAILED

Execution stopped because an actual error or failed acceptance condition prevents completion.

#### PAUSED

Work is intentionally suspended and may resume.

#### CANCELLED

The operator or system explicitly abandoned the Mission.

### 9.3 Do not overload status

A provider can be working while a Mission is `NEEDS_YOU` for another branch of work. Mission state should represent the operator's current relationship to the outcome, not merely the sum of worker process states.

---

## 10. Needs You — attention as a first-class surface

### 10.1 Why it matters

When Warden can run multiple agents/tasks, the operator should not babysit each stream.

The product becomes more valuable when the operator can leave work running and later see exactly what requires human judgment.

### 10.2 Global queue

`Needs You` should collect actionable items across Projects/Missions.

Examples:

```text
NEEDS YOU                                                   2

Settings multi-account
Plan ready for decision
[Review]

Warden release
Publishing package requires approval
[Review]
```

### 10.3 Working and Ready views

A broader Inbox/Home view can also summarize:

```text
WORKING                                                     3
GUI redesign                Codex · building
Competitor research         Gemini · researching
Regression verification     Jules · reviewing

READY                                                       1
Settings accounts           implementation complete
                             6 files · 148 tests passed
[Review]
```

### 10.4 Notification policy

Notify prominently only when:

- approval is needed;
- a decision is needed;
- requested review is ready;
- a Mission fails materially;
- a Mission completes if completion notification is useful.

Do not elevate routine tool events into global notifications.

---

## 11. Connected AI accounts

### 11.1 New mental model

Replace the primary notion of "Web Platforms" with **Connected AI**.

Connected AI represents real subscriptions, sessions, browser profiles, or official local provider clients available to Warden.

Example:

```text
CONNECTED AI

ChatGPT
Personal
● Signed in

Gemini
Personal
● Signed in

Gemini
Google Startup
● Signed in

HyperAgent
Primary
● Signed in

HyperAgent
Research
● Signed in

Claude
○ Disabled
```

### 11.2 Requirements

The UI should support:

- multiple accounts for the same platform;
- user-defined account names;
- persistent account/browser profile association;
- hide/show account in sidebar;
- pin/unpin;
- reorder;
- rename display label without changing provider identity;
- clear signed-in/signed-out/attention state;
- explicit account selected when a Mission uses it, if relevant;
- direct-open provider web surface when the operator wants it.

### 11.3 Security/auth boundary

Preserve existing repository rules:

- website authentication remains separate from official local Build-client authentication;
- never copy provider tokens into unrelated contexts;
- never silently switch users to API billing;
- remote sites stay sandboxed without privileged Node/IPC/filesystem/terminal/Brain access.

### 11.4 Provider/account identity in work cards

Show the actual provider/account when it helps explain or audit work:

```text
Research · Gemini · Startup
Build · Codex · local subscription
Review · Claude Code · Personal
```

Do not require the user to choose these manually for every Mission unless policy or preference demands it.

---

## 12. Dynamic staffing and agent representation

### 12.1 Stop hardcoding the team

The UI should not permanently imply:

```text
Claude UX
Codex Builder
Spark Research
Warden Captain
```

unless those are actual configured/active agents.

### 12.2 Capability-first routing

Preferred conceptual model:

```text
Need: research
→ choose suitable available research capability/provider/account

Need: implementation
→ choose suitable builder

Need: independent review
→ choose a different capable reviewer when available

Need: browser action
→ choose browser/computer-use capability
```

### 12.3 UI display

The operator mostly sees the Mission and work type.

Provider/agent identity appears as metadata:

```text
BUILD
Codex
Working
```

not as a permanently visible chat participant who must narrate its existence.

### 12.4 Advanced Agent Bench

A future/advanced Agent Bench may expose:

- configured agents;
- available providers;
- capabilities;
- policies;
- cost/subscription route;
- concurrency;
- health;
- account binding;
- model/version.

This should not be required to understand the default product.

---

## 13. Build capability migration

### 13.1 Do not throw away Simple Build

The current Build implementation contains valuable components:

- project selection;
- safe-workspace handling;
- mission templates;
- objective and acceptance criteria;
- structured provider execution;
- phase tracking;
- approvals;
- live activity;
- raw event toggle;
- apply/request changes/discard;
- undo;
- file changes;
- checks;
- proof/history;
- handoff;
- isolated worktree flow.

These should be **recomposed into the Mission model**, not deleted.

### 13.2 New mapping

Current:

```text
Talk to Warden
    ↓ handoff
Build
    ↓
Review surface
```

Target:

```text
Mission
├── conversation
├── objective
├── acceptance criteria
├── work units
├── terminal
├── changes
├── tests
├── review
├── apply/undo
└── proof
```

### 13.3 Consequential changes

Preserve the existing explicit-operator-decision boundary before agent work reaches the project where required by Warden's safety/Git model.

The GUI may make the review much easier, but it must not fake or bypass approval state.

---

## 14. Terminal experience

### 14.1 Default behavior

Warden may perform terminal work through its existing execution surfaces.

The Mission card summarizes it:

```text
TERMINAL
Codex
Installing dependencies · complete
Running tests · working
[Open terminal]
```

### 14.2 Inspection view

When opened:

```text
Warden is working

Codex
Installing dependencies

$ npm install
...
✓ complete

Running tests

$ npm test
...
148 passed
```

### 14.3 Commercial value

This is important for Warden's consumer story.

Other assistants often tell a non-developer:

> "Open your terminal and run…"

Warden should visibly do that work for them while allowing technically sophisticated users to inspect the same execution.

### 14.4 Advanced controls

Advanced mode may allow direct terminal interaction, terminal tabs, shells, Git commands, raw provider output, etc.

Default mode should not require it.

---

## 15. Review and proof

### 15.1 Completion card

Target completion experience:

```text
✓ DONE

Persistent Google account switching

Changed
6 files

Verified
✓ 148 tests
✓ Electron launched
✓ account survives restart
✓ Google session restored
✓ no unrelated files changed

Reviewed
Claude · no blockers

[See result] [Proof] [Undo]
```

### 15.2 Guided review order

When a user opens a completed code Mission, show information in this order:

1. **Outcome** — what now works.
2. **What changed** — plain-English summary.
3. **Verification** — what Warden actually checked.
4. **Preview/result** — when visual/runtime output exists.
5. **Files** — affected files.
6. **Diff** — implementation detail.
7. **Raw evidence** — advanced/audit detail.

Do not start a non-developer review with a raw diff.

### 15.3 Evidence levels

Recommended display vocabulary:

- `Claimed`
- `Observed`
- `Verified`
- `Reviewed`
- `Approved`

The underlying evidence model may map to existing Warden structures rather than inventing a second proof database.

### 15.4 Proof integrity

Never display a green verification state unless authoritative evidence exists.

Do not infer "tests passed" from agent prose.

Do not display screenshots as proof unless they were actually captured.

Do not display an independent review unless an independent reviewer actually ran.

---

## 16. Projects and Mission history

### 16.1 Project role

A Project is the stable boundary for:

- repository/workspace;
- active branch/Git context;
- relevant instructions;
- Brain context;
- connected browser profile preferences;
- Mission history;
- verification/proof history.

### 16.2 Mission history

Recent Missions should be accessible by Project and globally.

Each row can show:

```text
GUI redesign             Working       2m ago
Multi-account settings   Done          Today
Runtime 0.6.1            Done          Yesterday
```

### 16.3 Resume/restart

A restarted desktop should restore enough Mission/project state that the user understands what was happening without reconstructing context manually.

This does not imply that dead external processes are falsely shown as active. Restore durable state truthfully and reconcile live process state.

---

## 17. Home / Mission Control view

The default landing surface when no specific Mission is open should answer:

- What am I working on?
- What is Warden currently doing?
- Does Warden need me?
- What finished recently?
- What project was I last in?

Recommended structure:

```text
GOOD AFTERNOON / WARDEN

Needs You                                            1
[Release package requires approval]

Working                                              2
[GUI redesign · Codex]
[Research · Gemini]

Ready                                                1
[Settings multi-account · verified]

Recent Missions
...

Composer: Tell Warden what you want done…
```

Avoid turning Home into an analytics dashboard.

---

## 18. Default vs Advanced mode

### 18.1 Default mode

Default mode should emphasize:

- projects;
- Missions;
- conversation;
- work cards;
- Needs You;
- preview/results;
- guided review;
- connected AIs;
- proof.

### 18.2 Advanced mode

Advanced mode can reveal:

- direct terminal controls;
- Git branch/worktree detail;
- raw events;
- runner sessions;
- model gateway;
- MCP/A2A detail;
- Brain internals/graph;
- explicit provider/build tabs;
- low-level evidence records;
- orchestration internals.

### 18.3 Important rule

Advanced mode should reveal more information, not switch Warden into a completely different application with a different mental model.

---

## 19. Visual design direction

This ADR is primarily about information architecture, but the visual system should support the mental model.

### 19.1 Desired character

Warden should feel:

- serious;
- modern;
- capable;
- calm under load;
- information-dense when needed;
- approachable to a non-developer;
- more like an operating console than a hacker dashboard.

### 19.2 Avoid

Avoid:

- excessive neon/cyberpunk styling;
- dozens of colored pills competing for attention;
- permanent status lights for idle fictional agents;
- giant empty chat bubbles;
- heavy card nesting;
- walls of tiny metadata;
- raw tool logs in the main conversation;
- labels such as "control plane" in beginner-facing primary navigation unless they genuinely help.

### 19.3 Status color hierarchy

Use color sparingly and semantically.

Recommended hierarchy:

- neutral — idle/informational;
- accent — selected/active interaction;
- progress — real working state;
- warning — Needs You/attention;
- success — verified completion;
- error — actual failure.

Do not make every provider a permanently bright color.

### 19.4 Motion

Subtle motion is appropriate for:

- active work progress;
- context panel open/close;
- card status transitions;
- completed check transitions.

Avoid constant ambient animation that makes idle Warden look busy.

---

## 20. Responsive behavior

Warden is a desktop-first application but must remain usable in compact windows.

### Wide desktop

```text
[Left rail] [Mission/conversation] [Context work surface]
```

### Medium

```text
[Compact rail] [Mission] [optional overlay/context drawer]
```

### Narrow

```text
[Mission]
Navigation and context become drawers/sheets.
```

Acceptance should include at least:

- normal desktop packaged Electron window;
- compact desktop window;
- no clipped primary controls;
- keyboard focus remains usable;
- composer always reachable;
- Needs You and status remain discoverable.

---

## 21. Suggested UI data model

Implementation agents should first reuse existing authoritative stores/events and adapt them into a presentation model. Do **not** create a parallel fake state system merely to make the redesign easy.

Conceptual presentation types:

```ts
type MissionStatus =
  | 'draft'
  | 'working'
  | 'needs_you'
  | 'ready'
  | 'done'
  | 'failed'
  | 'paused'
  | 'cancelled';

type WorkKind =
  | 'plan'
  | 'research'
  | 'build'
  | 'browser'
  | 'terminal'
  | 'changeset'
  | 'test'
  | 'review'
  | 'approval'
  | 'proof'
  | 'checkpoint'
  | 'failure';

interface MissionSummary {
  id: string;
  projectId: string | null;
  title: string;
  objective: string;
  status: MissionStatus;
  createdAt: string;
  updatedAt: string;
  needsUser: boolean;
  activeWorkCount: number;
  verificationSummary?: VerificationSummary;
}

interface WorkItem {
  id: string;
  missionId: string;
  kind: WorkKind;
  title: string;
  status: string;
  provider?: string;
  accountLabel?: string;
  summary?: string;
  startedAt?: string;
  completedAt?: string;
  inspectView?: 'plan' | 'research' | 'preview' | 'browser' | 'terminal' | 'files' | 'diff' | 'tests' | 'proof' | 'raw';
  evidenceRefs?: string[];
}
```

These are conceptual targets, not mandatory new persisted schemas. Prefer adapters/selectors over duplicating authoritative state.

---

## 22. Existing implementation seams to inspect

Implementation agents must inspect current code before editing.

### Desktop renderer — primary migration area

Start with:

```text
desktop/src/renderer/index.html
desktop/src/renderer/index.ts
desktop/src/renderer/styles.css
desktop/src/renderer/simple-build.ts
desktop/src/renderer/copy.ts
```

Current renderer already contains substantial shell and Simple Build behavior. Reuse behavior where possible while changing composition.

### Desktop main process / provider / execution seams

Inspect relevant files before changing contracts:

```text
desktop/src/main/index.ts
desktop/src/main/platform-manager.ts
desktop/src/main/provider-auth.ts
desktop/src/main/oauth-policy.ts
desktop/src/main/build-providers.ts
desktop/src/main/cli-provider.ts
desktop/src/main/codex-adapter.ts
desktop/src/main/context-assembler.ts
desktop/src/main/evidence.ts
desktop/src/main/git-safe-loop.ts
desktop/src/main/handoff.ts
```

Do not casually modify main-process security or auth boundaries for a renderer redesign.

### Warden runtime

Inspect:

```text
docs/architecture/warden-agent-runtime.md
src/warden/... relevant runtime/tool registry files
```

The current runtime is real and model-driven. The GUI redesign should consume it, not replace it with another deterministic UI router.

### Embedded legacy/web UI

Inspect:

```text
web/warden/app.html
web/warden/app.js
web/warden/app.css
```

The current desktop Talk surface embeds this web UI. A major goal of the redesign should be reducing architectural duplication between the Electron shell and the embedded Warden shell.

Do not delete the web UI until all required desktop behavior has a replacement and tests prove no regression.

### Existing tests to preserve/extend

At minimum inspect and preserve relevant coverage in:

```text
desktop/tests/renderer-chrome.test.ts
desktop/tests/simple-build.test.ts
desktop/tests/run-store.test.ts
desktop/tests/evidence.test.ts
desktop/tests/context-handoff.test.ts
desktop/tests/providers.test.ts
desktop/tests/provider-auth.test.ts
desktop/tests/oauth-popup.test.ts
desktop/tests/git-safe-loop.test.ts
desktop/tests/build-providers.test.ts
desktop/tests/cli-provider.test.ts
desktop/tests/codex-events.test.ts
```

Also inspect existing browser/E2E Playwright tests under `tests/` before designing new selectors.

---

## 23. Architectural migration strategy

### Phase 0 — inventory and contract map

Before changing layout:

1. Map every current top-level renderer surface.
2. Map every IPC/API dependency used by Talk, Web Platforms, and Build.
3. Identify authoritative sources for:
   - active project;
   - conversation;
   - active runs;
   - plans;
   - tasks;
   - evidence;
   - provider/account sessions;
   - worktree/apply state.
4. Identify which data currently exists only in the embedded `web/warden` interface.
5. Create a migration matrix: **current capability → target Mission surface → source of truth → tests**.

Deliverable: a short implementation note committed with the feature branch or appended to this ADR if decisions materially change it.

### Phase 1 — shell and navigation

Goal: establish the new mental model without breaking execution.

Implement:

- new left rail hierarchy;
- Home/Warden primary surface;
- Projects + Recent Missions presentation;
- Needs You entry point;
- Connected AI section;
- contextual work-surface container;
- Advanced controls entry.

Temporary compatibility is acceptable:

- current Talk iframe may still power the conversation initially;
- current Build code may still power execution initially;
- old surfaces can be reachable via Advanced/legacy route while migration proceeds.

But the visible default navigation should already teach the new model.

### Phase 2 — Mission presentation layer

Goal: make the real runtime/task/run state appear as Mission work.

Implement adapters/selectors that produce:

- Mission summaries;
- human Mission states;
- work cards;
- Needs You items;
- provider/account metadata;
- verification/proof summaries.

No fake activity.

### Phase 3 — absorb Simple Build into Missions

Goal: remove the conceptual Build wall.

Move/recompose:

- objective;
- acceptance criteria;
- execution progress;
- approvals;
- changes;
- tests;
- review;
- apply/discard/undo;
- proof

into Mission + contextual work surface.

Keep the existing structured run logic and Git-safe loop unless a specific bug requires change.

### Phase 4 — Connected AI / multi-account UX

Goal: make subscriptions/accounts visible as resources.

Implement:

- multiple account entries per platform;
- rename/pin/reorder/hide;
- persistent profile/account association;
- account-aware work metadata;
- direct provider surface open;
- clear auth state.

Preserve OAuth and sandbox boundaries.

### Phase 5 — eliminate duplicate primary shells

Goal: Warden should not feel like Electron wrapping a second full Warden application.

Either:

- move primary Mission conversation rendering into the Electron renderer;
- or reduce embedded web UI to a headless/embedded surface without duplicate navigation/chrome.

Do not remove the legacy surface until equivalent behavior and tests exist.

### Phase 6 — demo polish and hardening

Goal: produce a trustworthy 45-second demo from a real installed build.

Complete:

- visual polish;
- state transition polish;
- loading/error states;
- compact window behavior;
- packaged Electron smoke;
- real runtime execution;
- screenshot/video proof path;
- no fake demo-only hardcoded states.

---

## 24. Priorities

### P0 — required before recording the flagship demo

1. **Unify Talk + Build under Mission UX.**
2. **Contextual right work surface** for Research / Terminal / Preview / Diff / Tests / Proof.
3. **Typed work cards** instead of agent narration.
4. **Needs You** attention queue/state.
5. **Truthful provider/agent identities** derived from real work.
6. **Proof completion card** with real verification.
7. **Clean default sidebar** centered on Projects/Missions rather than internal subsystems.
8. **Real packaged-build verification** of the new flow.

### P1 — strongly desired before public beta

1. Connected AI multi-account manager.
2. Pin/reorder/rename/hide connected accounts.
3. Mission history and restart restoration.
4. Full-screen/expanded Preview, Terminal, Diff, Research.
5. Guided review.
6. Human-readable checkpoints and Undo.
7. Strong compact-window support.

### P2 — power-user depth

1. Agent Bench.
2. Advanced orchestration telemetry.
3. Brain inspector/graph improvements.
4. Raw event explorer.
5. MCP/A2A debugging surfaces.
6. Model gateway detail.

---

## 25. Non-goals

This redesign must **not** become an excuse to rebuild the entire runtime.

Non-goals for the first implementation:

- rewriting `WardenAgentRuntime`;
- replacing working task/run stores without a demonstrated need;
- inventing a new proof database when existing evidence can be adapted;
- replacing Git-safe worktree behavior merely to simplify UI code;
- replacing official provider authentication with API keys;
- bypassing user approval boundaries;
- creating fake agent activity for prettier screenshots;
- building a full VS Code clone;
- building a full Slack clone;
- making every advanced Warden subsystem visible in the default navigation;
- designing a huge plugin marketplace before the Mission flow works;
- optimizing for mobile phone use before desktop UX is correct.

---

## 26. Hard guardrails from `AGENTS.md`

All implementation agents must preserve repository rules.

In particular:

- repository is the source of truth;
- preserve unrelated changes;
- never rewrite shared history;
- never commit credentials, `.env` files, browser profiles, run stores, generated packages, or local Brain data;
- remote websites remain sandboxed;
- website auth and official local Build-client auth remain separate;
- never copy provider tokens or silently switch to API billing;
- consequential agent work requires explicit operator decisions where Warden currently requires them;
- private Brain/mail/browser/server integrations remain optional;
- capabilities must be documented as they actually work;
- visible UI changes require real Electron smoke proof.

---

## 27. Agent collaboration model for this project

This document is intended to be usable by Agy, Codex, Jules, Claude, or another capable agent without requiring the operator to restate the product direction every session.

### Suggested role split

These are suggested roles, not permanent fictional personas.

#### Agy / architecture lead

Best tasks:

- inventory existing surfaces/contracts;
- design migration seams;
- reconcile runtime/UI truth;
- identify duplicated state;
- keep ADR updated when architecture decisions change.

#### Codex / implementation lead

Best tasks:

- renderer refactor;
- Mission components/presentation models;
- contextual work surface;
- migration of Simple Build behavior;
- test implementation;
- packaged build verification.

#### Jules / independent reviewer / parallel implementation

Best tasks:

- review architecture against current repo;
- identify regressions and hidden coupling;
- implement isolated components/tests in parallel;
- verify responsive/interaction states;
- review resulting diff against this ADR.

#### Claude / UX review where available

Best tasks:

- visual hierarchy;
- interaction clarity;
- copy;
- guided review behavior;
- screenshot critique;
- non-developer usability review.

### Parallel-work rule

Agents may work in parallel only when file ownership and interfaces are clear.

Suggested separation:

```text
Agent A: presentation model/selectors + tests
Agent B: shell/layout/styles
Agent C: contextual work surface / Mission cards
Agent D: independent review / browser smoke
```

Avoid multiple agents simultaneously rewriting `index.ts` or `styles.css` without coordination.

---

## 28. Required implementation workflow for each agent

Before editing:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/master
```

Read:

```text
AGENTS.md
this ADR
docs/architecture/warden-agent-runtime.md
desktop/architecture.md
```

Then inspect the specific files involved.

Do not start by generating a replacement UI from imagination.

### Before commit

Run relevant focused tests first, then the full desktop check.

Repository baseline requirement from `AGENTS.md`:

```bash
cd desktop
npm ci
npm run check
```

For Python-affecting changes:

```bash
PYTHONPATH="$PWD:$PWD/src" .venv/bin/python -m pytest \
  tests --ignore=tests/e2e --ignore=tests/browser -q
```

Before publication:

```bash
bash scripts/public_release_audit.sh
```

Visible UI changes additionally require an installed or packaged Electron smoke test under the normal Chromium sandbox.

### Required final proof format from implementation agents

Every implementation report should distinguish:

#### Proven

- exact files changed;
- tests actually run and results;
- installed/packaged app behavior actually observed;
- screenshots/browser checks actually captured;
- Git state.

#### Claimed but not proven

Anything inferred but not directly verified.

#### Regressions / unresolved issues

Explicitly list them.

#### Next command/check

Give the exact next verification action if anything remains uncertain.

---

## 29. Acceptance tests — product behavior

The redesign is not complete because screenshots look good. The following behavior must be demonstrably true.

### AT-01 — Warden is the default front door

Given the application starts with a valid project available,
when the main window loads,
then the user can immediately tell Warden what they want without selecting Talk, Build, or a provider first.

### AT-02 — no fake work

Given no runs/tasks are active,
then the UI must not display fictional agents as working.

Global work count must resolve to zero/Ready.

### AT-03 — Mission creation

Given the user requests a multi-step project outcome,
when Warden begins execution,
then a durable Mission/work representation appears and remains associated with the active project.

### AT-04 — real work card

Given a real provider/tool begins work,
then the Mission displays a typed work card whose identity/status comes from authoritative execution state.

### AT-05 — contextual inspection

Given a work card has inspectable output,
when the user opens it,
then the relevant Research/Terminal/Files/Diff/Tests/Proof view opens without leaving the Mission mental model.

### AT-06 — Needs You

Given a real execution step requires operator approval or decision,
then the Mission becomes visibly actionable and a global Needs You item appears.

When resolved, the item disappears or transitions truthfully.

### AT-07 — verification truth

Given tests/checks fail,
then the UI must not show the Mission as verified/done unless the Mission's actual acceptance policy permits completion despite that failure.

### AT-08 — proof drill-down

Given verification completes,
when the user opens Proof,
then they can see authoritative check/evidence detail supporting the summary.

### AT-09 — terminal not required for default user

A user must be able to initiate and complete the flagship demo Mission without manually typing terminal commands.

### AT-10 — terminal remains inspectable

The user can open the terminal/execution view and see actual command activity for a real structured run.

### AT-11 — project work does not auto-apply improperly

Existing Git/worktree approval semantics remain intact.

### AT-12 — connected AI account identity

When a provider/account is used and that identity is known, the UI can show the real account/provider metadata without exposing credentials.

### AT-13 — restart truth

After restarting the desktop app:

- durable Mission/project history restores;
- completed work stays completed;
- dead processes are not shown as live;
- live state is reconciled rather than blindly restored.

### AT-14 — compact window

At compact supported window sizes:

- navigation remains reachable;
- composer remains reachable;
- primary actions are not clipped;
- context work can still be opened/closed;
- no horizontal layout corruption blocks use.

### AT-15 — direct provider access survives

A user can still intentionally open a connected provider's genuine web surface with the correct named profile/session.

---

## 30. Acceptance tests — technical regression gates

At minimum, existing relevant desktop tests must continue passing and new tests should cover the Mission presentation model.

Required categories:

- renderer chrome/navigation;
- provider configuration;
- provider auth;
- OAuth popup behavior;
- state persistence;
- run store;
- context handoff;
- evidence/proof;
- Git-safe loop;
- Simple Build behavior during migration;
- structured provider event rendering;
- no fake activity;
- Needs You derivation;
- Mission state derivation;
- context panel routing.

Prefer deterministic tests for state derivation. Use Playwright/Electron smoke for actual interaction/layout proof.

---

## 31. Flagship demo proof gate

The GUI is not demo-ready until this exact style of flow can be recorded in one coherent installed-build session without fake states.

### Demo objective

User says:

> **Research the best multi-account approach and fix Settings. Make sure it actually works.**

### 0–5 seconds — intent

Visible:

- Warden primary surface;
- active Warden project;
- connected AI accounts unobtrusively visible;
- clean composer.

User enters the objective.

### 5–12 seconds — Warden interprets

Warden responds approximately:

> I'll research the account model first, implement the selected approach in an isolated workspace, then verify the installed app.

A real Research card appears.

### 12–18 seconds — research

Research transitions to complete.

Example metadata:

```text
Research complete
Gemini · Startup
3 approaches compared
1 recommendation
[Open research]
```

Open briefly to show actual content.

### 18–27 seconds — implementation

Real Build card appears:

```text
Codex
Building → Verifying
6 files changed
[Open work]
```

Open work surface.

Actual terminal activity is visible.

The user does not type commands.

### 27–35 seconds — preview/result

Warden opens the real application/result.

The new account switching/settings behavior is visible.

### 35–41 seconds — verification

Verification card shows real checks, for example:

```text
148 tests passed
Electron launched
Restart persistence passed
```

Numbers must match the real run; never hardcode the example values.

### 41–45 seconds — proof

Warden synthesizes:

> Done. Multi-account switching persists across restart.

Completion/Proof card is visible.

### Demo failure conditions

Do not record the flagship demo if any of these are true:

- fake static agent statuses are visible;
- user must manually navigate to Build to continue;
- user must type shell commands;
- raw database/tool IDs leak into conversation;
- Warden claims verification not actually run;
- a second unrelated Warden navigation shell is visibly fighting the desktop shell;
- broken buttons or dead controls are visible;
- OAuth/session switching is staged but not real;
- the app cannot survive the demonstrated restart/persistence claim;
- major text is clipped at the recording window size.

---

## 32. Commercial usability test

Before recording, give the installed app to a person who has not followed Warden's architecture and ask only:

> "What do you think this app does?"

Then show them a Mission in progress and ask:

> "What is happening right now?"

Then show a blocked Mission and ask:

> "Does the app need anything from you?"

Then show a completed Mission and ask:

> "How do you know it actually worked?"

The target is that they can answer without being taught the terms Captain, Brain, Runner, MCP, worktree, or FinishJob.

Those systems are advantages precisely because Warden can hide their complexity until needed.

---

## 33. Migration compatibility map

| Current concept | Keep? | Target location |
|---|---:|---|
| Talk to Warden | Yes | Primary Warden/Mission surface |
| Team Chat | Partially | Mission conversation; group-chat behavior only when useful |
| Build | Capability yes, destination no | Mission work + contextual surface |
| Simple Build | Yes | Mission implementation/review flow |
| Web Platforms | Capability yes, destination secondary | Connected AI + direct-open provider |
| Individual platform sidebar | Yes, redesigned | Connected AI accounts |
| Captain | Yes | Warden internal capability; advanced details when useful |
| Brain | Yes | Warden memory/context capability; advanced inspector |
| Tasks | Yes | Mission/work state; advanced task board if useful |
| Runner Sessions | Yes | Advanced/debug state |
| Proof | Yes, elevate | Mission completion + Proof contextual view |
| Model Gateway | Yes | Advanced/settings |
| Brain Graph | Yes | Advanced/Brain inspection |
| Raw events | Yes | Advanced per-work/Mission inspection |
| Terminal tabs | Yes | Advanced/context work surface |
| Apply / discard / undo | Yes | Mission review actions |
| Acceptance criteria | Yes | Mission objective/details |

---

## 34. Suggested implementation components

Names are illustrative; agents should fit repo conventions rather than forcing a framework rewrite.

Potential renderer modules:

```text
mission-model.ts
mission-view.ts
mission-cards.ts
mission-context-panel.ts
mission-inbox.ts
connected-ai-view.ts
project-rail.ts
proof-view.ts
```

Do not split files merely to satisfy this list. The goal is to prevent `index.ts` from becoming an even larger monolith while retaining clear ownership.

Potential pure derivation helpers are especially valuable because they are easy to test:

```ts
deriveMissionStatus(...)
deriveNeedsYouItems(...)
deriveActiveWorkCount(...)
deriveWorkCards(...)
deriveVerificationSummary(...)
```

These helpers must consume authoritative state.

---

## 35. Error and empty-state requirements

### No project

Do not show a blank dashboard.

Explain what Projects mean and offer:

- open folder/repository;
- create sample project;
- continue conversation without project where valid.

### No provider connected

Warden may still answer with available local/runtime capability where possible.

For work requiring a provider, show a clear action:

> Connect an AI to continue this Mission.

### Provider auth expired

Show account-specific attention state in Connected AI and, if blocking a Mission, surface it in Needs You.

### Work fails

Failure card should show:

- what failed in human language;
- whether partial changes exist;
- whether anything was applied;
- best next action;
- optional raw detail.

### Warden runtime unavailable

Fail visibly and truthfully. Do not substitute fake local responses that make the UI look alive.

---

## 36. Accessibility and keyboard requirements

At minimum:

- semantic buttons/inputs;
- visible focus states;
- keyboard traversal of left rail, Mission cards, context tabs, composer;
- Escape closes drawers/context surfaces where appropriate;
- no color-only status communication;
- work cards expose status text;
- live updates use appropriate `aria-live` regions without reading every terminal line;
- compact window remains usable at keyboard-only level.

---

## 37. Performance expectations

Do not let the new Mission UI turn every status tick into a full renderer rebuild.

Prefer:

- event/state coalescing;
- compact status updates;
- lazy loading of heavy diffs/logs/research;
- contextual view fetch only when opened;
- bounded Mission history in the initial render;
- reuse of context-economy principles where server payloads are involved.

The main conversation must remain responsive while terminal/test streams are active.

---

## 38. Telemetry/product validation

If/when product analytics are connected, the GUI redesign should make these events measurable:

```text
mission_created
mission_started
mission_needs_user
mission_user_resolved
mission_ready
mission_completed
mission_failed
work_card_opened
context_view_opened
proof_opened
connected_ai_opened
provider_account_added
provider_account_switched
mission_resumed
undo_used
```

Primary product metrics:

1. user creates first Mission;
2. Mission reaches real work;
3. Mission reaches verified result;
4. user understands/resolves Needs You;
5. user returns and resumes Project/Mission;
6. user uses more than one connected AI through Warden;
7. user opens Proof/result rather than needing raw logs.

Do not optimize for raw chat-message count.

---

## 39. Decisions intentionally made now

The following are explicit architectural/product decisions for implementation unless later revised in this ADR:

1. **Warden, not Team Chat, is the default product identity of the primary surface.**
2. **Mission is the durable work container.**
3. **Build becomes a Mission capability, not a peer top-level mental model.**
4. **Work cards replace routine agent narration.**
5. **Needs You becomes a first-class operator attention concept.**
6. **Connected AI replaces Web Platforms as the default resource metaphor.**
7. **Multiple accounts per provider are first-class.**
8. **Actual provider/agent identity is shown truthfully and dynamically.**
9. **Terminal remains visible/inspectable but is not required for beginner flow.**
10. **Proof is elevated to a primary completion experience.**
11. **Advanced internals remain available through progressive disclosure.**
12. **The 0.6.1 real agent runtime is preserved and consumed rather than replaced for this redesign.**

---

## 40. Questions agents may resolve during implementation

Agents do not need to stop work for these unless a decision blocks safe implementation. Prefer evidence from the current repo and record the chosen answer.

### Q1 — Mission persistence

Can existing GroupChat/task/run/Finish stores cleanly represent Mission history, or is a thin durable Mission index needed?

Default bias: build a thin index/adaptor before creating a large new store.

### Q2 — embedded web UI migration

Should Mission conversation move fully into Electron in the first major PR, or should the iframe be temporarily retained behind a new shell?

Default bias: choose the path that gets to one coherent product surface fastest without breaking the real runtime.

### Q3 — context panel implementation

Should context work use one panel with internal view routing or multiple panel components?

Default bias: one consistent panel contract with typed views.

### Q4 — global vs per-project Needs You

Default: global queue with project labels and project-filtered subsets.

### Q5 — provider auto-selection UX

Default: Warden selects based on capability/configuration; operator can inspect/override in advanced Mission details.

### Q6 — terminology

Default user-facing terms:

- Warden
- Project
- Mission
- Needs You
- Connected AI
- Proof

Avoid introducing more nouns unless necessary.

---

## 41. Definition of done for the GUI redesign milestone

This milestone is done when all of the following are true:

### Product clarity

- a new user lands on Warden, not an architecture menu;
- Projects and Missions are understandable without explanation;
- Build is not required as a separate navigation concept;
- provider accounts read as connected resources;
- Needs You clearly communicates required operator attention.

### Functional truth

- Warden's conversation uses the real 0.6.1 agent runtime;
- active work states derive from real tasks/runs;
- no fake agent activity exists;
- work cards open real output;
- approval state is authoritative;
- proof reflects actual evidence;
- apply/undo safety semantics still work.

### Developer power

- terminal remains accessible;
- files/diff/tests/proof remain inspectable;
- direct connected-provider surfaces remain accessible;
- advanced controls expose deeper system detail.

### Verification

- relevant focused tests pass;
- full `desktop` check passes;
- Python suite passes if Python changed;
- packaged/installed Electron smoke passes;
- compact window smoke passes;
- flagship demo flow is completed against real state;
- screenshots/video show no fake or broken controls;
- Git working tree is clean at final handoff;
- branch/master SHAs are reported.

### Demo readiness

A 45-second screen recording can show:

```text
ask → research → build → real terminal → preview → verify → proof
```

without explaining Warden's internal architecture and without asking the user to manually operate developer tooling.

---

## 42. Final product statement

The GUI should make this promise obvious:

> **You already have powerful AI tools. Warden gives them shared project context, coordinates the work, handles the technical machinery, brings you in when your judgment matters, and proves the result.**

Everything in the default interface should reinforce that promise.

If a UI element mainly explains Warden's internal implementation rather than helping the user understand, direct, inspect, approve, or verify work, it belongs behind progressive disclosure.

---

## 43. Source/reference index

### Warden repository

- `AGENTS.md`
- `docs/architecture/warden-agent-runtime.md`
- `docs/architecture/context_economy.md`
- `docs/architecture/warden_mcp2_interop.md`
- `desktop/architecture.md`
- `desktop/src/renderer/index.html`
- `desktop/src/renderer/index.ts`
- `desktop/src/renderer/simple-build.ts`
- `desktop/src/renderer/styles.css`
- `desktop/src/main/platform-manager.ts`
- `desktop/src/main/provider-auth.ts`
- `desktop/src/main/evidence.ts`
- `desktop/src/main/git-safe-loop.ts`
- `web/warden/app.html`
- `web/warden/app.js`
- `web/warden/app.css`

### External interface research

- Cursor 3.0: https://cursor.com/changelog/3-0
- Cursor 3.4: https://cursor.com/changelog/3-4
- OpenAI Codex app: https://openai.com/index/introducing-the-codex-app/
- OpenAI release notes: https://help.openai.com/en/articles/6825453-release-notes
- Claude Code Desktop: https://code.claude.com/docs/en/desktop
- Replit changelog: https://docs.replit.com/updates/2025/04/18/changelog
- Replit agent UI changelog: https://docs.replit.com/updates/2026/01/16/changelog
- Replit Task Board: https://docs.replit.com/references/agent/task-board
- Replit Agent build flow: https://docs.replit.com/learn/build-with-agent
- Linear changelog: https://linear.app/changelog
- Linear Diffs / Guided Review: https://linear.app/changelog/2026-05-27-linear-diffs
- Warp Agents: https://www.warp.dev/agents

---

## 44. Agent start-here checklist

When an agent is assigned work from this ADR:

- [ ] Read `AGENTS.md`.
- [ ] Read this entire ADR.
- [ ] Read `docs/architecture/warden-agent-runtime.md`.
- [ ] Inspect current branch/status/SHA before editing.
- [ ] Inspect the current implementation instead of assuming file structure.
- [ ] Identify the authoritative state source for every UI state being changed.
- [ ] Do not create fake demo activity.
- [ ] Do not rewrite the real runtime to simplify presentation code.
- [ ] Preserve auth/security/Git approval boundaries.
- [ ] Add/adjust deterministic tests for state derivation.
- [ ] Run focused tests.
- [ ] Run `cd desktop && npm run check`.
- [ ] Perform real packaged/installed Electron smoke for visible UI changes.
- [ ] Verify compact layout.
- [ ] Report proven vs unproven claims.
- [ ] Report exact Git branch/SHA/status.
- [ ] Update this ADR if implementation evidence forces a material architecture change.
