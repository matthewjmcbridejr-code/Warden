# Warden — 5-Minute Demo Script

**URL:** `http://127.0.0.1:6969/web/warden/app.html`  
**CLI:** `scripts/warden-chat`

> Warden is a local-first AI command center that remembers everything you work on, answers questions about what happened, develops plans, dispatches coding agents, and tracks proof.

---

## The Story (Say This Up Front)

> "I built a personal AI command center. It watches what I work on — git commits, files I change, sites I browse, searches I run, things I type — and stores all of it as memory. Then I can ask it what happened, get a briefing on any project, develop a plan, and dispatch coding agents to execute it. The model gateway routes every AI call intelligently so nothing private leaves the machine unless I decide it should."

---

## 1. Open Warden (15s)

Open `http://127.0.0.1:6969/web/warden/app.html`

Point out the four tabs: **Command · Warden Chat · Memory Chat · Gateway Status**

> "Four tabs. That's the whole product. No clutter."

---

## 2. Memory Chat — Ask What You Did (60s)

Click **Memory Chat** tab.

Type: `What did I just work on?`

Warden will pull from:
- Git commits (branch, files changed, commit messages)
- Browser activity (pages visited, searches, things typed)
- Shell history

**What to show:** Warden knows the recent commits, knows what sites were visited, knows what was searched. No manual logging.

> "I didn't write any of that down. Warden captured it automatically — from git hooks, from a Chrome extension that captures every page I visit, every search I run, every form I fill out."

Follow up: `What did I search for today?`

Expected: Google searches like `kali ai tools`, `was ask jeeves retired`, `warden memory architecture`.

> "That's a real Google search I ran during testing. Warden remembered it."

---

## 3. Warden Chat — Project Status (45s)

Click **Warden Chat** tab.

Type: `Where are we at with Warden?`

Warden Agent will use tools — git log, file inspection, memory context — and give a structured briefing.

> "This agent has access to the actual repo. It can read files, check git history, run searches. It's not guessing."

---

## 4. Command — Develop a Plan (60s)

Click **Command** tab.

Show the hero: `What do you want to build?`

Type a small, real goal: `Add a --plain flag to the mem subcommand in warden-chat`

Select **Claude Code** chip. Click **Develop Plan**.

Wait ~5s. Captain returns 3–5 bounded steps.

> "Captain is the orchestrator. It breaks the goal into steps that a coding agent can execute one at a time. I review the plan before anything runs. Nothing is automatic."

Point out the Deploy button is disabled:

> "Deploy is greyed out. That's intentional — dispatching to a real agent requires a private runner to be configured. The plan is ready; execution is a separate gate."

---

## 5. Gateway Status — Supporting Infrastructure (30s)

Click **Gateway Status** tab.

Show the provider health table and alias summary strip.

> "This is the supporting infrastructure. Six model aliases — local Ollama, Groq for speed, OpenRouter for depth. Every AI call in Warden routes through this. Private content never goes to the free tier. That's the privacy guard."

Keep this brief. Gateway is the engine, not the product.

---

## 6. CLI Demo (30s)

In terminal:

```bash
scripts/warden-chat mem "What did I search for today?"
```

Then:

```bash
scripts/warden-chat ask "What files changed in the last three commits?"
```

> "Same memory, same agents, from the terminal. No browser required."

---

## 7. Close (15s)

> "Everything I work on goes into Warden memory. I can ask about it anytime — in the UI, in the terminal, or from another agent. The Chrome extension captures browsing silently. Git hooks capture commits. The memory watcher captures file changes and shell history. Nothing is manual. Warden just knows."

---

## What's Live vs. What's Not

| Feature | Status |
|---|---|
| Memory capture (git, files, shell) | Live via memory watcher daemon |
| Memory capture (browser) | Live via Chrome extension |
| Memory Agent chat | Live |
| Warden Agent chat (tools) | Live |
| Captain plan generation | Live (OpenRouter key required) |
| Agent dispatch (Deploy) | Not yet — requires private runner |
| LiteLLM proxy routing | Live (Ollama local, cloud via env keys) |

---

## Proof Point

Memory end-to-end was verified on 2026-06-29:

- Chrome extension installed, real session performed
- Activity captured: Google searches, Snyk browsing + form input, GitHub OAuth, Wikipedia, Hyperagent
- Memory Agent recalled activity accurately without being told what to look for
- Proof memory ID: `proof-browser-ext-e2e-verified`
- 68 total memories at time of proof, 34 from browser extension
