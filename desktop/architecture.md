# Warden AI Desk architecture

## Legacy inventory and classification

| Existing component | Classification | Desktop decision |
|---|---|---|
| `src/warden/projects.py` project/worktree model | Reuse behind a future adapter | Useful project authority; no direct Electron dependency yet. |
| `src/warden/run_history.py` run/proof fields | Reuse behind a new run-store adapter | Inform the normalized run model without copying its storage implementation. |
| Brain ingest and MCP servers | Reuse unchanged | Future proof/memory writes should call the existing boundary. |
| Agent registry | Migrate later | Capability discovery is useful, but current CLI-oriented lanes are not structured provider adapters. |
| `src/warden/api.py` tmux runner | Legacy; keep intact | Hidden from the desktop. Optional `LegacyRunnerAdapter` may be added later. |
| Codex prompt injection, quick replies, `capture-pane`, transcript polling | Deprecate for provider integration | Existing workflows remain intact, but new desktop code has no dependency on them. |
| Browser DOM capture/scraping | Not used | Provider WebContents receive no injected scripts. |

Nothing in the legacy backend is removed or behaviorally changed by this desktop pass.

## Capability boundaries

Warden keeps three layers distinct:

1. A **Web Platform** is an untrusted remote website in a sandboxed `WebContentsView`. Its definition controls navigation and profile selection only. It receives no preload or Warden capability.
2. A **Structured Provider** is a provider-native App Server, SDK, CLI, headless, MCP, or ACP adapter implementing `BuildProvider`.
3. A **Warden Extension** is a separately installed, explicitly trusted adapter. A URL definition can never create or imply one.

Web platforms use named profile partitions (`persist:warden-profile-*`). The partition belongs to the profile, not to a platform, so intentional profile sharing works without copying credentials. Domain trust is per platform. Clearing storage enumerates only that platform's configured origins and never clears the entire partition; the UI still warns that Chromium cookies are registrable-domain scoped and can affect related sites.

Project workspaces persist the repository, selected profile/platforms, split layout, execution mode, terminal references, and active run. Web definitions, project state, and durable run state are separate records so a project switch can restore the whole working context without conflating a website with an agent adapter.

## Structured provider boundary and authentication

`src/shared/types.ts` defines `BuildProvider`, normalized run events, capabilities, authentication reports, inputs, approvals, and lifecycle operations. Provider-specific payloads survive on `NormalizedRunEvent.providerPayload`, so normalization does not erase provider detail.

Structured Build is subscription-first. Warden asks each official local client for status or performs a bounded read-only entitlement probe, but it never reads provider credential files or handles OAuth tokens. Subscription child processes remove API credential variables from their inherited environment. Gemini additionally receives `GEMINI_DEFAULT_AUTH_TYPE=oauth-personal`. Authentication and refresh remain entirely inside `codex`, `claude`, `gemini`, or `grok`.

The UI reports `subscription authenticated`, `API-key authenticated`, `disconnected`, `installed but not authenticated`, `unsupported`, or `unknown entitlement`. Every persisted run snapshots the active authentication/billing source. API-key execution is opt-in: it is unavailable unless an API credential is already present in the launch environment, requires a billing warning and per-run approval, and is never selected or resumed silently.

The persistent run record includes provider session/thread ID, authentication source, prompt, project, working directory/branch, changed files, diff, commands/tests, approvals, normalized events with redacted raw metadata, result, and Brain proof state. No adapter simulates completion or proof.

## Codex App Server target

The installed `codex-cli 0.144.3` can generate its version-matched schema with:

```bash
codex app-server generate-json-schema --out /tmp/warden-codex-schema
```

The next adapter slice should:

1. Spawn `codex app-server` with stdio pipes, never a shell command string.
2. Exchange newline-delimited JSON-RPC messages.
3. Perform `initialize` and `initialized` once per connection.
4. map `thread/start` and `thread/resume`, then `turn/start`, to `BuildProvider` operations.
5. Normalize item/turn notifications while preserving their raw payloads.
6. Bridge command, file-change, and permissions approval requests to explicit Warden approval UI.
7. Implement `turn/interrupt`, transport failure recovery, cancellation, and resume.
8. Persist only non-secret thread/run references through a Warden run-store adapter.

`CodexAppServerProvider` now implements this lifecycle over stdio. It uses `untrusted` approvals and `workspace-write` sandboxing, records normalized events plus raw redacted payloads, persists the Codex thread ID, and resumes it after restart. It does not fall back to CLI keystroke injection.

## Structured provider implementations

- Codex uses App Server JSON-RPC with `account/read`, `thread/start|resume`, `turn/start|interrupt`, streamed notifications, and bidirectional approval responses. `account/read` is called with `refreshToken: false`.
- Claude uses the official Claude Code headless client with `stream-json`, explicit session IDs, resume, cancellation, and the client-owned Claude.ai login. The adapter preserves raw structured events. It does not impersonate the unsupported interactive permission prompt; unapproved tools stay denied by Claude Code.
- Gemini uses the official Gemini CLI headless client with `stream-json`, session IDs, resume, cancellation, and forced Google-account authentication for subscription runs. A failed entitlement probe is reported honestly and blocks dispatch.
- Grok Build uses its official `streaming-json` headless interface with session IDs, resume, cancellation, and cached `grok login` authentication. API environment credentials are excluded from subscription runs.

Local Terminal remains a separate PTY execution mode. None of these adapters call the legacy tmux prompt-injection runner or scrape terminal text.

The current non-Codex headless clients do not expose a Warden-controlled approval callback in their stream interfaces, so their capability reports set `approvals: false` and leave unapproved tool actions to the official client policy. Codex App Server remains the fully bridged approval implementation. Grok ACP and Gemini ACP are the next path to richer provider-native approval negotiation without weakening this boundary.
