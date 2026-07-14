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

## Structured provider boundary

`src/shared/types.ts` defines `BuildProvider`, normalized run events, capabilities, inputs, approvals, and lifecycle operations. Provider-specific payloads survive on `NormalizedRunEvent.providerPayload`, so normalization does not erase provider detail.

The future persistent run record can include run/thread ID, prompt, project, working directory/branch, terminal transcript reference, changed files, diff, commands/tests, approvals, usage, result, and Brain proof state. This pass defines the boundary only; it generates no fake runs or proof.

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

## Other structured providers

- Claude target: the official [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview), preserving its native permission and session events behind `BuildProvider`.
- Gemini target: official [Gemini CLI headless mode](https://google-gemini.github.io/gemini-cli/docs/cli/headless.html), using structured output/session support rather than terminal scraping.
- Grok Build target: official [Grok Build headless and scripting interface](https://docs.x.ai/build/cli/headless-scripting), including streamed output and resumable sessions where supported.

These adapters are deliberately disconnected in the UI today. No provider result is simulated.
