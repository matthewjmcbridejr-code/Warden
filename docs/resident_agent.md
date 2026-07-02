# Warden Resident Agent

The Warden resident agent is a single, local-first conversational operator
that lives under `src/warden/resident/`. It gives Matt one place to talk to
Warden naturally — over Telegram first — instead of memorizing slash
commands, while staying cheap to run: routing is deterministic wherever
possible, and any LLM call is an explicit, opt-in escalation.

## What it is

- **One resident process** that polls Telegram, routes messages, and calls
  into existing Warden capabilities (memory, watchers, mail, WebStudio,
  agent/session inspection) rather than reimplementing them.
- **Local-first**: all state lives in a local SQLite database
  (`_mctable/resident/resident.sqlite` by default). No cloud dependency is
  required for the deterministic paths.
- **Approval-gated**: anything risky (sending email, DNS/production
  changes, stopping/running agents, file changes) goes through an approval
  queue instead of executing directly.

## Modules

| Module | Purpose |
|---|---|
| `agent.py` | Orchestration: routes inbound messages, bounds reply length |
| `router.py` | Deterministic slash-command parser + keyword classifier |
| `messages.py` | Inbound/outbound message dataclasses |
| `memory.py` | Thin adapter over `personal_memory.py` / `memory_agent.py` |
| `watchers.py` | Watcher model + DNS/website checkers, hash-based dedup |
| `email_adapter.py` | Wraps `mail/gmail.py` + `mail/gmail_imap.py`, draft-only by default |
| `warden_client.py` | Thin client over `agent_registry.py` / `agent_dispatcher.py` |
| `tools.py` | Bounded tool registry callable by the router |
| `approvals.py` | Approval queue: approve/deny/execute-if-safe |
| `telegram.py` | Polling transport with allowlist + offset persistence |
| `state.py` | SQLite persistence (offsets, watchers, approvals, audit log) |
| `formatting.py` | Telegram-safe truncation/formatting, "reply MORE" |
| `config.py` | Env loading + secret redaction |

## BotFather setup

1. Open a chat with [@BotFather](https://t.me/BotFather) on Telegram.
2. Send `/newbot`, follow the prompts, and BotFather will give you a bot
   token that looks like `123456789:AA...`.
3. **Never paste this token into a chat, issue, PR, or log message.** Keep
   it only in `configs/warden_resident.env` (gitignored, mode 600).
4. To find your numeric Telegram user id, message
   [@userinfobot](https://t.me/userinfobot) — this is what goes into
   `TELEGRAM_ALLOWED_USER_IDS`.

## Setup script usage

```bash
scripts/warden_resident_setup.sh
```

This prompts for the bot token (input hidden, `read -s`), the allowed user
and chat IDs, and writes everything to `configs/warden_resident.env`
(mode 600, gitignored). It never echoes the token back and only prints the
variable names it set plus the next commands to run.

## Allowlisting

- `TELEGRAM_ALLOWED_USER_IDS` and `TELEGRAM_ALLOWED_CHAT_IDS` are
  comma-separated lists of numeric Telegram IDs.
- If **neither** is configured, the transport fails closed — every sender
  is rejected. There is no "allow everyone" mode.
- Unauthorized senders are rejected silently (no reply sent) and the
  rejection is recorded in the audit log — but the *allowlist contents
  are never logged or echoed back*, even in the rejection event.

## Slash commands

```
/start                 — confirm the agent is online
/help                  — list commands + a few NL examples
/status                — agents + sessions summary
/memory <query>        — search memory (capped to 5 results)
/watchers              — list configured watchers
/agents                — list registered agents
/sessions              — list active dispatched sessions
/approvals             — list pending approvals
/approve <id>          — approve a pending action
/deny <id>             — deny a pending action
```

## Natural language examples

These are handled by the deterministic keyword classifier in `router.py` —
**no LLM call happens** for any of them:

- "check my email" → email summary (capped, incremental)
- "draft a reply to Bob" → draft only, never sends
- "send it" → approval-gated; asks a clarifying question if recipient/body
  aren't already established
- "what changed overnight" → watcher events + running sessions + recent
  memory (a tier 2/3 context pack)
- "run webstudio audit on unlck" → WebStudio SEO/file-presence audit
- "watch dns for example.com" → creates a DNS watcher (approval required for
  non-sandbox domains)
- "what do I know about X" → memory search
- "save this to memory" → remember(note)
- "what are agents doing" → list registered agents
- "stop that session" → matches a running session, returns a safe dry-run
  response (no executor exists yet to actually kill a dispatched process)

Anything that doesn't match a slash command or a known pattern is
**ambiguous** — see the Efficiency section below for what happens next.

## Watchers

Watcher kinds: `dns`, `website`, `email`, `agent`, `reminder`, `generic`.

- **DNS watcher**: resolves NS/A/CNAME with a bounded timeout. Prefers
  `dnspython` if installed, falls back to `dig`, then a plain
  `socket.gethostbyname` A-record check. Never raises.
- **Website watcher**: checks HTTP status with a short timeout (via
  `requests` if installed, else `urllib`).
- **Dedup**: watchers only notify when `last_result_hash` changes (SHA1 of
  the result payload). Repeated identical results never re-notify.
- **Backoff**: after repeated failures, cadence is multiplied by
  `2^failure_count` (capped at 8x) so a broken watcher doesn't hammer a
  dead endpoint.

## Email modes

`EMAIL_MODE` = `disabled` (default) | `mock` | `gmail` | `imap`.

- **disabled**: every email operation returns a clear "email disabled"
  response. This is the safe default — no mail is ever fetched.
- **mock**: an in-memory deterministic mailbox for testing/demos; no
  network calls.
- **gmail** / **imap**: wraps the existing read-only `mail/gmail.py` and
  `mail/gmail_imap.py` providers. **Sending is never actually implemented**
  in this build — `send()` always returns a dry-run / "executor not
  implemented" response, even when approved and `EMAIL_DRY_RUN=false`,
  because no live send path exists in the underlying mail providers.
  `draft()` always succeeds locally and never sends.

## Approval flow

1. A risky action (email send, DNS/production change, agent stop/run,
   file change) creates an `Approval` with a redacted payload, a risk
   level, and a 24-hour expiry.
2. Matt reviews with `/approvals`, then `/approve <id>` or `/deny <id>`.
3. `ApprovalQueue.execute()` only runs the action if a safe executor is
   registered for that `action_type`; otherwise it returns a dry-run
   "executor not implemented" response rather than guessing at an unsafe
   action.
4. Pending approvals older than their expiry auto-transition to `expired`
   the next time they're read.

## Production domain guard

`unlck.shop` is hardcoded as the only sandbox domain
(`config.SANDBOX_DOMAINS`). Any DNS/deploy action against any other domain
is routed through an approval (`risk_level=high`) before anything happens,
reusing the same policy already enforced in
`src/warden/webstudio/dns_migration.py` — production domains stay
audit-first, sandbox domains can be migrated directly.

## Systemd usage

```bash
sudo cp deploy/systemd/warden-resident-telegram.service.example \
  /etc/systemd/system/warden-resident-telegram.service
# edit User=, WorkingDirectory=, and paths if your checkout differs
sudo systemctl daemon-reload
sudo systemctl enable --now warden-resident-telegram
journalctl -u warden-resident-telegram -f
```

The service runs from the repo root, sources `configs/warden_resident.env`,
runs `python -m warden.resident.telegram`, restarts on failure, and opens
**no public port** (Telegram polling is outbound-only).

## Troubleshooting

- **"TELEGRAM_BOT_TOKEN is not set"** — re-run
  `scripts/warden_resident_setup.sh` or check `configs/warden_resident.env`
  is sourced.
- **Bot doesn't respond** — confirm your Telegram user id is in
  `TELEGRAM_ALLOWED_USER_IDS`; unauthorized senders are rejected silently
  by design (check the resident SQLite `audit_log` table for
  `telegram_rejected` events).
- **"email disabled"** — set `EMAIL_MODE=mock` to test, or `gmail`/`imap`
  once a mail account is connected via the existing connector store.
- **DNS/deploy action blocked** — expected for any domain other than
  `unlck.shop`; use `/approvals` then `/approve <id>`.

## Efficiency

See `docs/telegram_resident_agent.md` for the full efficiency/cost-control
section (deterministic routing, context tiers, caps, model profiles, deep
synthesis triggers).
