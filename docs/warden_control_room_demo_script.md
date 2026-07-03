# Warden Control Room — 3-Minute Demo Script

Use private service: `http://127.0.0.1:8125/web/warden/index.html`

For screenshot/demo visuals without a live mission: `?demo=1` (clearly labeled simulated).

## 1. Open Warden (15s)

Open Control Room. Point out:

- Warden by Marius Systems
- Left nav: Control Room, Missions, Agents, Runs, Evidence, Proof Gates, Runner Sessions
- Top bar: Live indicator, Refresh, Command palette

## 2. Explain Control Room (20s)

Hero message: **Supervised control room for AI coding agents.**

Warden tracks missions, runs, transcripts, evidence, and proof gates before anything moves forward.

## 3. Mission snapshot (25s)

Show mission progress card (or honest idle state in real mode).

- Real mode: “No active mission” with next actions (Open Captain, Configure agents, View runner sessions)
- Demo mode: active mission with progress bar

## 4. Connected agents (20s)

Right rail **Connected Agents**:

- Codex CLI — private runnable when configured
- Jules — planning only, not executable
- Captain — orchestrator when configured

## 5. Proof gates (25s)

Right rail **Proof Gates** + Proof Gates tab:

- Passed / pending / blocked / needs evidence counts
- Human review required — no auto-dispatch

## 6. Runner session safety (25s)

Right rail **Runner Sessions**:

- Active / max / stale counts
- Limit warning when at capacity
- Dry-run cleanup (show candidates, no kills)

## 7. Dry-run cleanup (20s)

Click **Dry-run cleanup** on private service.

Show modal: `dry_run: true`, candidates listed, `killed: []`.

## 8. Next Move (15s)

Right rail **Next Move** — operator guidance only; buttons route to manual UI.

## 9. Human approval gates (20s)

Open a run or gate review (if available). Emphasize:

- Approve / block / request more evidence
- Mark step complete manually after approval
- No automatic progression

## 10. Close (15s)

> AI agents work faster when Warden keeps them supervised.

Public runner disabled. Jules not executable. Secrets never printed.