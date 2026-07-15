# Warden AI Desk architecture

## Why Electron

Provider authentication—especially Google and OpenAI login—has been unreliable in Linux system webviews used by WebKitGTK-based shells. Electron ships Chromium, the compatibility model proven by multi-service wrappers such as Ferdium and Rambox, while still allowing Warden to isolate remote content from local capabilities. Chromium compatibility is not permission to weaken the sandbox.

## Capability boundaries

Warden keeps three layers distinct:

1. A **Web Platform** is untrusted remote content in a sandboxed `WebContentsView`. Its definition controls URL, icon, category, profile, domain trust, ordering, and layout only.
2. A **Structured Provider** is a provider-native App Server, SDK, CLI, headless, MCP, or ACP adapter implementing `BuildProvider`.
3. A **Warden Extension** is a separately installed, explicitly trusted adapter.

A URL can never create or imply structured execution.

The local renderer has one narrow preload API with context isolation, Node integration disabled, and sandboxing enabled. Remote views have **no preload at all**, no Node integration, no Warden IPC, and no injected scripts. Permissions are denied by default. URL policy rejects file, script/data, internal, and privileged navigation; HTTPS is the default, with localhost HTTP allowed only in explicit development mode.

## Browser profiles and OAuth

Named profiles map to persistent `persist:warden-profile-*` Chromium partitions. A partition belongs to the profile, not a platform. Platforms assigned to one profile intentionally share that Warden-managed session; separate profiles never share cookies. Warden never imports or decrypts Chrome cookies.

Unknown navigation/auth domains produce a native decision: allow once, trust for the platform, open in the system browser, or cancel. OAuth popups remain visible, use the originating partition/opener, retain the remote-content security preferences, follow approved redirect chains, then close/refocus correctly. Safe diagnostics record event type, protocol/host class, outcome, and fingerprints—not URL paths/queries, headers, cookies, passwords, tokens, or remote console text.

The Chat overflow is an Electron native `Menu`, not renderer HTML, because `WebContentsView` is a separate native surface that can cover DOM overlays. Its IPC validates the main renderer, platform ID, and anchor coordinates. Destructive actions remain native confirmations.

## Project restoration

`StateStore` persists platforms, named profiles, projects, window bounds, and stopped terminal metadata with atomic JSON replacement. A project owns repository path, branch snapshot, profile, selected/split platforms, Chat/Build workspace, execution mode, terminal IDs, and active run. Corrupt definitions are skipped; corrupt state is preserved before safe defaults recover.

Simple Build and Developer Mode are two views over that same project and run state. Simple Build starts Codex in an isolated `warden/task-*` worktree. On acceptance, Warden stages the complete isolated tree, synthesizes one commit parented to the recorded base, verifies that the real project is still clean and unchanged, and applies it through an abortable cherry-pick. This captures normal App Server working-tree edits without relying on agent-created commits or repository Git identity. Undo requires a clean project and records a separate revert commit; it never rewrites history.

Browser data and run records stay separate from platform definitions. Removing a platform preserves profile data. Clearing configured site data is separately confirmed and warns that registrable-domain cookies may affect related sites in the same profile.

## Structured runs

`BuildProvider` defines authentication reports, capability reports, start/resume/cancel/approval operations, and a normalized event stream. Provider-specific payloads survive only after redaction in `NormalizedRunEvent.providerPayload`.

`RunManager` snapshots the authentication/billing source and persists run status, provider session/thread IDs, context, approvals, events, changed files, git diff, commands/tests, final response, handoffs, and proof. Interrupted work can be inspected and resumed after restart. No adapter simulates completion or Brain proof.

### Subscription-first authentication

Official clients own sign-in, credential storage, and refresh. Warden performs bounded status/entitlement probes but does not read credential files or OAuth tokens. Subscription child processes remove API credential variables; Gemini additionally selects its Google-account auth mode. API execution is optional, visibly selected, and requires per-run billing approval.

| Provider | Interface | Structured features |
|---|---|---|
| Codex | App Server JSON-RPC | account status, thread start/resume, turn start/interrupt, stream, file/command events, bidirectional approvals |
| Claude | Claude Code headless stream JSON | session IDs, stream, resume, cancellation; no claimed Warden approval callback |
| Gemini | Gemini CLI headless stream JSON | session IDs, stream, resume, cancellation, entitlement guard; no claimed Warden approval callback |
| Grok | Grok headless streaming JSON | session IDs, stream, resume, cancellation; no claimed Warden approval callback |

Local Terminal is a separate PTY execution mode and is never presented as a structured provider.

## Context, handoffs, and proof

Context assembly can include repository instructions, discovered skills, git branch/status, scoped local Warden memories, and optional context from the private Brain service. A handoff compacts the goal, result, changed files, commands/tests, approvals, and remaining work for another provider. Save proof always attempts a local artifact first; the optional Brain response is recorded as saved, failed, or unavailable.

## Legacy isolation

The older FastAPI service, Brain/MCP tools, task board, and workspace authority remain available. The old tmux/Codex prompt injection, keystrokes, `capture-pane`, transcript polling, and terminal scraping are legacy and are not desktop dependencies. They are not removed in 0.3.0, but new desktop structured work does not route through them.
