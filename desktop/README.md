# Warden AI Desk

Warden AI Desk is a local Linux command center for project work. The Electron shell combines sandboxed, login-persistent AI websites, managed project terminals, and subscription-first structured agent runs without treating those three capability levels as interchangeable.

## Install, verify, and package

```bash
cd desktop
npm install
npm run check
npm start
npm run package:deb
```

The Debian artifact is written to `desktop/dist-electron/`. Packaging does not publish or release it. The package installs Electron Builder's normal Chromium sandbox/AppArmor support; Warden does not ship a permanent `--no-sandbox` workaround.

## Custom AI platforms

Chat uses editable `WebPlatform` definitions rather than hardcoded provider tabs. Claude, ChatGPT, Gemini, and Grok are initial ordinary definitions. HyperAgent, Perplexity, and Microsoft Copilot are available from the same starter-preset picker used to create any custom platform.

Each definition has a stable ID, category, start URL, icon, named browser profile, project associations, trusted first-party/authentication domains, main/split availability, navigation state, ordering, pinning, and enabled state. Definitions and last trusted URL restore after restart. Removed custom platforms go to a restorable list; removing one never deletes browser data.

Named profiles map to persistent `persist:warden-profile-*` Chromium partitions. Platforms assigned to one profile intentionally share that profile's login state; profiles never share a partition and Warden never imports Chrome cookies. A platform `WebContentsView` has no preload, Node integration, terminal, filesystem, Brain, token, or IPC access. Context isolation, Chromium sandboxing, web security, HTTPS validation, navigation constraints, popup handling, and deny-by-default permissions stay enabled.

Unknown OAuth/navigation domains pause and offer **Allow once**, **Trust for this platform**, **Open in system browser**, or **Cancel**. Downloads pause for an explicit save approval. “Clear this site's data” is an origin-scoped troubleshooting action behind the overflow menu. Cookies may be stored at registrable-domain scope, so the confirmation honestly warns that related sites in the same named profile can also be affected.

## Projects and Build

A project stores its repository directory, named browser profile, selected/split platforms, Chat/Build workspace, execution mode, terminals, and active run reference. Switching projects restores that desktop context. Terminal metadata survives restart as stopped sessions; Warden never claims the PTY process itself survived.

Structured Build is separate from web platforms:

- Codex uses the installed Codex App Server with ChatGPT subscription login, streamed events, approvals, evidence, cancellation, and resume.
- Claude uses the official Claude Code headless client and its Claude.ai subscription login.
- Gemini uses the official Gemini CLI headless client and Google-account entitlement.
- Grok uses the official Grok headless client and `grok login` state.

Provider authentication remains owned by those clients. API-key billing is an explicitly approved fallback and is never selected silently. Durable runs retain normalized/redacted events, provider session references, approvals, diffs, commands/tests, handoffs, and honest local/Brain proof state. The legacy tmux prompt-injection runner is not a desktop dependency.
