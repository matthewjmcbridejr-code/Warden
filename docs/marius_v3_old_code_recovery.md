# Marius v3 Old Code Recovery

## 1. Repos inspected
- `marius`
- `marius-mind-code`
- `marius-trace`
- `marius-radar-foreman`
- `marius-trader`

## 2. Old Telegram files found
- `marius/docs/marius_telegram_bot.md`
- `marius/src/integrations/telegram_bot.py`
- `marius/src/memory/telegram_memory.py`

## 3. Old memory/persona files found
- `marius/memory/marius_persona.md`
- `marius/memory/matt_facts.md`
- `marius/memory/projects/hybrid-agent-os.md`

## 4. Old deep routing/thinking/operator patterns found
- `marius/_mctable/handoffs/examples/telegram-deep-routing.md`

## 5. What felt better in old Marius/OpenClaw/Hermes
- The visible terminal trace during processing (operator mode).
- Telegram integration serving as a remote personal agent interface.
- Quick personal agent behavior (direct answers without excessive generation delay from mandatory context retrieval).

## 6. What to port
- Trace routing syntax for the console (`[route]`, `[brain]`, `[model]`, `[done]`).
- The skeleton of `telegram_bot.py`, adapted for the new Warden API namespace.
- Model recommendation commands to surface capabilities based on models present.

## 7. What not to port
- Invasive watchers/surveillance.
- Unnecessary desktop bloat/frameworks.
- Hidden reasoning / massive chain-of-thought dumps.
- Full `python-telegram-bot` logic without cleanup for the current local-first `/chat` API.

## 8. Security risks / secrets to avoid
- Do not log or commit `TELEGRAM_BOT_TOKEN`.
- Do not expose local ports to 0.0.0.0.
- Restrict Telegram to `MARIUS_TELEGRAM_ALLOWED_CHAT_IDS`.

## 9. Proposed Marius v3 architecture
- **Console Mode:** `/think`, `/deep`, trace strings, local defaults, fast iteration.
- **Telegram Bridge:** Read-only operator UI + brain save/recall, tightly bound to `127.0.0.1:6969`.
- **Model Truth:** Persists across components.

## 10. Implementation checklist
- [ ] Brain OFF by default in `scripts/marius_chat.py` (casual mode).
- [ ] Upgrade `marius console` to Operator Console v3 with trace lines.
- [ ] Add `marius model recommend` command logic.
- [ ] Implement `src/marius/integrations/telegram_bot.py` using old codebase structure but aligned with API.
