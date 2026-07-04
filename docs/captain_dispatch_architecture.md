# Captain Deck dispatch: how it works, and where to improve it

This documents the real-CLI dispatch path added on top of Captain Deck's planner
(`src/warden/api.py`, `src/warden/captain_plans.py`, `src/warden/agent_registry.py`,
`src/warden/resident/watchers.py`). Verified live end-to-end on 2026-07-04 with a real
`codex exec` dispatch (see "Live smoke test" below).

## How it works today

1. **Plan** — Captain generates a plan (OpenRouter, if a key is configured; otherwise
   the Marius gateway; otherwise a deterministic local template). Each step names an
   `agent_id` (`codex_cli`, `claude_code_cli`, or `grok_build_cli`).
2. **Dispatch** — `POST /captain/plans/{id}/steps/{id}/dispatch` reads the step's
   `agent_id`, resolves its launch command from `CLI_EXEC_ARGV` (api.py), and launches
   it non-interactively inside a tmux session with the CLI's own auto-approve flag
   (`codex exec -s workspace-write`, `claude -p --permission-mode acceptEdits`,
   `grok -p --always-approve`). A hard timeout (`CLI_DISPATCH_TIMEOUT_SECONDS`, default
   30 min) bounds a hung process. A thin Marius-gateway call logs a one-line dispatch
   note before launch — best-effort, never blocks dispatch.
3. **Watch** — dispatch creates a `captain_dispatch` watcher
   (`src/warden/resident/watchers.py`) polled via
   `POST /captain/plans/{id}/watchers/poll` (frontend polls this every 10s while
   Captain Deck is open). The watcher checks whether the tmux session still exists:
   - gone → `completed` → opens a pending proof gate, does **not** complete the step.
   - still running past 20 minutes → `stalled` → step marked `needs_review`, stops.
   - tmux check itself fails → `error` → step marked `needs_review`, stops.
4. **Gate** — a human reviews the proof gate (transcript, diff, whatever evidence is
   attached) and approves/blocks/requests more evidence via
   `POST /gates/{id}/decision`.
5. **Advance** — on **approve**, the endpoint completes the step and, only if the plan
   has `auto_advance: true`, immediately dispatches the next queued step. No gate
   approval → no advance. This is the one mandatory human checkpoint in the loop.

Execution mode is explicitly YOLO within a single step (no per-action confirmation
inside the CLI session) but never across steps without a human decision in between.

## Live smoke test proof

Ran a real 2-step plan (`codex_cli`) against this repo with the private runner enabled:
step 1 created a throwaway file, watcher detected clean exit and opened a gate
(did not auto-complete), gate approved manually, step 2 auto-dispatched and confirmed
the file, its gate approved, plan reached `status: completed`. Full decision log,
gate records, and run history were all populated correctly. Cleaned up afterward
(file removed, no tmux sessions left running).

## Where to improve — concrete follow-ups, roughly in priority order

1. **The Marius gateway `UnboundLocalError` bug is still open.** `ProviderGateway.chat()`
   crashes if called with a system-role message already in `history`, because the
   context-building block that defines `brain_pack` is skipped in that case, but
   `brain_pack` is referenced unconditionally later. Worked around in
   `_build_captain_plan_via_gateway`/`_captain_dispatch_decision` by never passing a
   system message, but the root cause in `src/marius/provider_gateway.py` isn't fixed.
   (Already flagged as a separate background task.)

2. **CLI launch flags will drift.** `CLI_EXEC_ARGV` (api.py) hardcodes each CLI's
   unattended-mode flag as of the versions installed 2026-07-04. Codex, Claude Code,
   and Grok Build are all actively developed and flag names/behavior can change across
   releases. There's no version pinning or flag-validation check — a CLI update could
   silently break dispatch (wrong flag → CLI errors immediately, which the watcher
   would correctly catch as `error`/`stalled`, but it's worth a periodic
   `<binary> --help` sanity check, e.g. in CI or a startup healthcheck).

3. **"Guards later" — smarter approval within a step.** Today a dispatched CLI runs
   fully unattended for the whole step (YOLO). The safer alternative discussed but not
   built: watch the CLI's own interactive approval prompts (reusing the existing
   `_send_key_to_codex_runner`/`ALLOWED_QUICK_REPLY_KEYS` quick-reply mechanism) and
   auto-approve routine actions while pausing on destructive-looking ones (delete,
   force-push, `rm -rf`, secrets). This would keep each CLI's own built-in guardrails
   active instead of bypassing them entirely.

4. **Single-poll watcher scheduling.** The watcher only gets checked when something
   calls `POST /captain/plans/{id}/watchers/poll` — currently just the frontend polling
   loop while Captain Deck's modal is open. If nobody has the modal open, a dispatched
   step just sits there until someone opens it again. There's no background
   scheduler/cron in this codebase (the existing `WatcherService.run_due()` only runs
   inside the resident agent's own reasoning loop). Worth adding a lightweight
   periodic job (or wiring into an existing cron-like mechanism, e.g.
   `mcp__ccd_directory` or a systemd timer) so long-running dispatches get noticed even
   with the browser closed.

5. **Antigravity isn't a real dispatch target.** It was on the original list of CLI
   subscriptions but turned out to be a GUI editor launcher (`antigravity [paths...]`),
   not a headless coding-agent CLI — there's no `-p`/`exec`/non-interactive mode to
   hook into. Left out of `BUILTIN_CLI_AGENTS`. If a future Antigravity release adds a
   headless mode, it can be added the same way Claude Code/Grok Build were.

6. **No cost/quota awareness.** Dispatch has no concept of how much of your Codex/
   Claude/Grok subscription quota a step might use, and no per-plan or per-day cap.
   Auto-advance chaining multiple steps could burn through usage limits without
   warning if run unattended for a long plan.

7. **Watcher persistence lives in a separate sqlite file
   (`_mctable/resident/resident.sqlite`)** from the plan JSON store
   (`_mctable/captain/plans.json`) and run history. They're linked only by the
   `plan_id`/`step_id`/`run_id` embedded in the watcher's `query` JSON blob — there's no
   foreign-key integrity between the two stores, so a corrupted/hand-edited plan file
   could leave orphaned watchers (harmless — they'd just poll a stale tmux session name
   and report `completed`/nothing to do — but worth knowing about if debugging weird
   watcher state).

8. **Manual "Dispatch Step" launches Codex in interactive mode still, unattended
   dispatch is Captain-only.** `_start_codex_runner` (the original interactive+TUI
   path) is untouched and still used for any *non*-Captain dispatch (e.g. launching a
   session directly via `/sessions/{id}/runner/start` without `execution_mode:
   "unattended"`). This was a deliberate scope decision to avoid touching the existing
   human-supervised flow, but means there are now two different Codex launch
   mechanisms in the codebase — worth consolidating once the interactive path's users
   are confirmed to not need it anymore.
