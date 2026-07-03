# Warden Public Beta — Test Guide

**For:** Matt's brother (non-developer tester)  
**What Warden is:** A local-first AI command center. You describe a goal, Warden creates a plan, dispatches steps to AI agents, and remembers what happened.  
**What "beta" means:** Core features work. Agent execution requires a local runner that isn't set up in this build — dispatched steps are saved as memory records instead of running.

---

## How to Open Warden

Make sure Matt's machine is running, then open in your browser:

```
http://127.0.0.1:6969/web/warden/app.html
```

You should see a dark-themed page with a sidebar on the left.

---

## The Four Sections

Click any section name in the left sidebar to switch.

| Section | What it does |
|---|---|
| **Command** | Type a goal → create a plan → dispatch steps |
| **Marius Agent** | Ask questions — it checks git history, memory, GitHub |
| **Memory Chat** | Ask what you've been working on, what got blocked, decisions made |
| **Gateway Status** | Technical — shows which AI providers are connected (you can ignore this) |

---

## Try This: The Core Loop (5 minutes)

### Step 1 — Create a Plan

1. Click **Command** in the sidebar (it's the default)
2. You'll see a welcome card explaining the basics — read it, then dismiss it with ✕
3. In the text box, type something like: `Add a dark mode toggle to the settings page`
4. Click **Develop Plan**
5. Warden creates a 3–5 step plan. Each step shows the goal and which agent would run it.

### Step 2 — Dispatch a Step

1. Click **Dispatch Step** next to Step 1
2. Because the local runner isn't set up, you'll see a yellow notice:  
   *"Runner unavailable — blocked attempt saved to Memory"*
3. This is expected — the step was recorded, not skipped
4. Two buttons appear: **Ask Memory what happened** and **Ask Marius Agent**

### Step 3 — Ask Memory What Happened

1. Click **Ask Memory what happened** (or navigate to Memory Chat manually)
2. Type: `What did the last agent run do?`
3. Warden should show you the blocked attempt — what step it was, why it was blocked, and the memory ID

### Step 4 — Ask Marius a Follow-up

1. Click **Marius Agent** in the sidebar
2. Try one of the starter buttons, or type: `What got blocked in my last captain dispatch?`
3. Marius pulls from memory and git context
4. The **Marius Trace** panel on the right shows what tools Marius used to answer

---

## What to Look For (Feedback)

Things that would be helpful to flag:
- Anything confusing or unclear (label, button, message)
- Any button that does nothing or produces an error
- Anything that looks broken
- Wording that only a developer would understand
- Anything you'd want to know before using the product

---

## What's Not Working in This Build

| Feature | Status |
|---|---|
| Running actual agent code | Not set up — steps are saved as memory records |
| Gmail/Outlook/iCloud connection | Keys not configured — providers shown but `configured: false` |
| Ollama AI (local model) | May be offline — Memory Agent uses fallback mode |
| Gateway live routing | Works for route preview; cloud providers need API keys |

---

## If Something Breaks

- Reload the page — most state is server-side
- Check the URL is still `http://127.0.0.1:6969/web/warden/app.html`
- If the page won't load at all, the API process may need a restart — ask Matt

---

## Quick Reference

```
http://127.0.0.1:6969/web/warden/app.html   ← main app
http://127.0.0.1:6969/api/mcharness/health  ← API health (should say "ok": true)
```
