# Warden — Quickstart

> **Warden is a local-first AI command center that remembers project activity, answers questions about what happened, develops plans, dispatches coding agents, and tracks proof.**

---

## Prerequisites

- Python 3.11+
- `.venv` with dependencies: `pip install -e .`
- Ollama running: `ollama serve`
- (Optional) Cloud keys in `~/.config/warden/cloud_keys.env` for Captain + cloud models

---

## 1. Start Warden API

```bash
cd /home/matt/workspaces/warden/mcharness-public-export
.venv/bin/python -m uvicorn src.warden.app:app --host 0.0.0.0 --port 6969 --log-level warning
```

---

## 2. Open the UI

```
http://127.0.0.1:6969/web/warden/app.html
```

Four tabs: **Command · Warden Chat · Memory Chat · Gateway Status**

---

## 3. Install the Chrome Extension

```
chrome://extensions → Developer mode → Load unpacked → browser-extension/
```

Warden captures silently: every URL, search queries, typed text, selections, clipboard, GitHub, YouTube, ChatGPT/Claude turns.

---

## 4. Start the memory watcher

```bash
systemctl --user start warden-memory-watcher
```

Captures git commits, branch switches, file changes, shell history.

---

## 5. Verify health

```bash
curl -sS http://127.0.0.1:6969/api/mcharness/health
curl -sS http://127.0.0.1:6969/api/mcharness/memory/health
```

---

## 6. Ask Warden

```bash
scripts/warden-chat ask "Where are we at with Warden?"
scripts/warden-chat mem "What did I work on today?"
scripts/warden-chat mem "What did I search for?"
scripts/warden-chat chat      # interactive Warden Agent REPL
scripts/warden-chat memory    # interactive Memory Agent REPL
```

---

## 7. Run tests

```bash
.venv/bin/pytest tests/ -x -q
```

---

## Product Loop

```
1. Ask Warden Chat  → "What's happening right now?"
2. Ask Memory Chat  → "What happened before? What did I decide?"
3. Command tab      → Type goal → Develop Plan (Captain)
4. Deploy           → Coding agent executes (requires private runner)
5. Review proof     → Commits, test results stored as memories
6. Repeat
```

---

## Model Gateway (supporting infrastructure)

Routes every AI call to the right model. View live: Gateway Status tab.

| Alias | Use | Provider |
|---|---|---|
| `warden-local` | Fast, private, free | Ollama |
| `warden-fast` | Everyday chat | Groq |
| `warden-free` | Public tasks only | OpenRouter free |
| `warden-code` | Code gen + tool calls | Groq 70b / Cerebras |
| `warden-deep` | Planning + reasoning | OpenRouter claude/gpt-4o |
| `warden-embed` | Embeddings | Ollama |

Privacy guard blocks private content from `warden-free` (OpenRouter logs).
