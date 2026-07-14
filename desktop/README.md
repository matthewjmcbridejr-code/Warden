# Warden AI Desk

The first usable Linux desktop shell for Warden. Electron supplies Chromium-backed, login-persistent tabs for Claude, ChatGPT, Gemini, and Grok; the Build workspace supplies managed interactive PTYs. Provider sessions are isolated from each other and never exposed to Warden's renderer.

## Install and run

```bash
cd desktop
npm install
npm start
```

Development currently uses the same deterministic build-then-launch command:

```bash
npm run dev
```

## Verify and package locally

```bash
npm run check
npm run package:linux
npm run package:deb
```

`package:linux` creates unpacked Linux artifacts under `desktop/dist-electron/`; it does not publish or release them.

On Linux installations where Chromium's SUID helper or unprivileged user namespaces are disabled, Electron will refuse to start rather than silently drop its process sandbox. Configure the host's Electron/Chromium sandbox according to the distribution policy; use `--no-sandbox` only for disposable headless smoke tests, never for normal use.

## Security and session behavior

- Provider content uses Electron `WebContentsView`, never an iframe and never the Warden preload.
- Every provider has its own `persist:warden-*` partition. Cookies and storage survive application restarts but are not shared between providers.
- Provider permissions are denied by default. Standard provider and OAuth navigation stays in the originating provider partition; unrelated links open in the system browser.
- **Clear session** deletes only the selected provider's cookies/cache/storage after confirmation.
- Google, Microsoft, Apple, GitHub, and provider-specific login flows require manual live verification because their behavior changes independently of Warden.

## Build workspace

Local Terminal uses `node-pty` and xterm.js. It supports multiple named sessions, working-directory selection and validation, interactive input, resize, status, command history, display clearing, and explicit process termination.

Non-secret desktop state is atomically written under Electron's per-user application-data directory. On restart, terminal names/directories/history are restored as **stopped** metadata; Warden never claims the PTY process survived.

Codex is connected through the installed Codex App Server. A run has a durable Warden record, normalized streamed events, approval requests, repository context, git/test evidence, local proof, and a compact cross-provider handoff. Interrupted runs retain the Codex thread ID and can be resumed after restarting the application.

Claude, Gemini, and Grok Build remain visible and honestly disconnected until their provider-native adapters are implemented. See [architecture.md](architecture.md) for the integration seam and legacy classification.
