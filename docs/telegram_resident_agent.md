# Telegram Resident Agent — Setup & Efficiency Guide

This document covers the Telegram-specific parts of the resident agent
(`src/warden/resident/telegram.py`) plus the efficiency/cost-control model
shared by the whole resident agent. See `docs/resident_agent.md` for the
general architecture, slash commands, watchers, email modes, and approval
flow.

## Quick start

```bash
scripts/warden_resident_setup.sh
set -a && source configs/warden_resident.env && set +a
PYTHONPATH='.:src' .venv/bin/python -m warden.resident.telegram
```

## BotFather setup (never paste tokens into chat)

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`.
2. Copy the token it gives you directly into
   `scripts/warden_resident_setup.sh`'s hidden prompt (`read -s`) — never
   paste it into a Telegram chat, a GitHub issue, or a log line.
3. Get your numeric user id from [@userinfobot](https://t.me/userinfobot).

## Allowlisting

`TELEGRAM_ALLOWED_USER_IDS` / `TELEGRAM_ALLOWED_CHAT_IDS` are the only way
in. No allowlist configured = fail closed (nobody gets through). Rejections
are silent to the sender and logged to the audit trail without ever
exposing the allowlist itself.

## Offset persistence

`TelegramTransport` persists the Telegram `getUpdates` offset via
`state.py` (`offsets` table), so a restart resumes from where it left off
instead of replaying old updates or losing messages sent while the process
was down.

## Retry / backoff

Network errors during polling back off exponentially (1s → 2s → 4s ... up
to 60s), resetting to 1s after a successful poll. This avoids hammering
Telegram's API during an outage.

---

## Efficiency: how the resident agent stays cheap

The resident agent is designed so that **the common case never touches an
LLM**. This section explains exactly how, and how to tune it.

### 1. Deterministic routing before any LLM call

Every inbound message goes through, in order:

1. **Slash command parse** (`router.parse_slash_command`) — pure regex/string
   parsing, zero cost.
2. **Keyword-intent classifier** (`router.classify`) — a fixed, ordered list
   of compiled regex patterns covering every required NL example ("check my
   email", "draft a reply", "what changed overnight", "watch dns for X",
   "what do I know about X", "save this to memory", "what are agents
   doing", "stop that session", etc). Also zero cost.
3. **Ambiguous fallback** — only reached when *neither* of the above
   matched. This is the *only* path that may call synthesis, and only if
   `RESIDENT_ENABLE_DEEP_SYNTHESIS=true`.

Tests in `tests/test_resident_agent.py` assert directly that obvious
intents (slash commands, "check my email", "what do I know about X", "what
changed overnight") result in **zero synthesis invocations** — a mock
synthesis function is injected and its call count is checked after each
routing decision.

### 2. Context tiers

The resident agent loads context in increasing tiers, only as far as a
given intent actually needs:

- **Tier 0** — no context. Slash commands like `/start`, `/help`.
- **Tier 1** — single bounded lookup. `/memory <query>` → up to 5 memory
  results; `/watchers` → watcher list; email summary → up to 10 messages.
- **Tier 2** — a small combined pack. "what changed overnight" pulls
  watcher results + active sessions + recent memory (each individually
  capped) and concatenates short summaries — still no LLM call.
- **Tier 3** — full synthesis context (git log, shell history, browser
  visits, board tasks, memories) via `memory_agent.gather_context()` — only
  reached if the ambiguous-fallback path is taken *and* deep synthesis is
  enabled.

### 3. Cost controls / caps

| Control | Default | Purpose |
|---|---|---|
| `RESIDENT_MAX_CONTEXT_ITEMS` | 8 | Cap on items pulled into a Tier 2 context pack (e.g. recent memory count in "what changed overnight") |
| `RESIDENT_MAX_RESPONSE_CHARS` | 900 | Telegram replies are truncated past this length; full text is cached for a "reply MORE" follow-up |
| Memory search cap | 5 | `memory.MemoryAdapter.search()` / `.recent()` never return more than 5 results regardless of requested limit |
| Email summary cap | 10 | `email_adapter.EmailAdapter` caps summarize/search results at `DEFAULT_SUMMARY_CAP=10` |
| Session tail cap | 40 lines | `warden_client.WardenClient.session_tail()` caps log tail output |
| Watcher notify dedup | — | Hash-based — a watcher never re-notifies for an unchanged result, avoiding redundant reply generation |
| Watcher backoff | up to 8x cadence | Failing watchers back off exponentially instead of retrying (and potentially notifying about) the same failure repeatedly |

### 4. Model profile config

`RESIDENT_MODEL_PROFILE` = `fast` (default) | `balanced` | `deep`. This
mirrors the profile concept already used elsewhere in Warden/Marius
(`model_profiles.py`) — it's read by the synthesis path (when reached) to
pick how much model budget to spend. The deterministic routing paths never
consult this setting at all, since they never call a model.

### 5. When deep synthesis triggers

Deep synthesis (a real LLM call via `memory_agent.chat()` / `run_agent()`)
only fires when **both** of the following are true:

1. The message did not match any slash command or keyword-intent pattern
   (`router.classify()` returned `"ambiguous"`).
2. `RESIDENT_ENABLE_DEEP_SYNTHESIS=true` in the environment.

If `RESIDENT_ENABLE_DEEP_SYNTHESIS` is `false` (the default), ambiguous
messages get a static, zero-cost nudge back toward `/help` or a rephrase —
no model call, no cost, ever, for unmatched input.

### 6. Tuning the `RESIDENT_MAX_*` env vars

- Raise `RESIDENT_MAX_CONTEXT_ITEMS` if "what changed overnight" summaries
  feel too thin; lower it to save tokens/response time on a slow link.
- Raise `RESIDENT_MAX_RESPONSE_CHARS` if you want longer Telegram replies
  before truncation kicks in (Telegram's hard message limit is ~4096
  chars — stay well under it).
- Set `RESIDENT_ENABLE_DEEP_SYNTHESIS=true` only if you want the agent to
  attempt a real conversational answer for genuinely open-ended questions;
  leave it `false` for a pure command-and-watcher operator with zero LLM
  spend.
