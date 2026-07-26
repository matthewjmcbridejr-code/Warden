# Warden AI Desk desktop

The Electron application is Warden's project-centered Linux workstation. It combines persistent sandboxed AI websites, local PTYs, and subscription-first structured provider runs while keeping those trust levels separate.

## Run locally

```bash
npm ci
npm run dev
```

`npm run dev` performs the same deterministic bundle used by production and opens Electron. Use a separate OS test account or named Warden browser profile for disposable authentication testing.

## Verify and package

```bash
npm run typecheck
npm test
npm run build
npm run package:deb
```

`npm run check` combines typecheck, tests, and the production build. `package:deb` writes to `dist-electron/` and never publishes. Do not launch with a permanent `--no-sandbox` flag.

## Source map

```text
src/main/       Electron lifecycle, IPC, WebContentsViews, PTYs, runs, adapters
src/preload/    narrow typed renderer API; never attached to remote content
src/renderer/   local application chrome and project/run UI
src/shared/     provider-neutral state, platform, auth, event, and run contracts
tests/          policy, persistence, OAuth, menu, adapter, evidence, and UI tests
assets/         application icon
```

## Three boundaries

- A **Web Platform** is an untrusted website. Claude, ChatGPT, Gemini, Grok, HyperAgent, and custom URLs all use the same editable definition model.
- A **Structured Provider** is a deliberate integration with an official local App Server, CLI, SDK, headless, MCP, or ACP interface.
- A **Warden Extension** is a separately installed trusted adapter.

Remote views have no preload or privileged IPC. Adding a URL never grants Build access.

## State and recovery

On Linux, Electron normally stores Warden data under `~/.config/Warden AI Desk/`:

- `desktop-state.json` — projects, platforms, profiles, layout, and stopped terminal metadata
- `Partitions/` and Chromium data — named browser profile sessions
- `runs/` — redacted durable run records, evidence, handoffs, and proof
- `diagnostics/platform-events.jsonl` — privacy-filtered navigation/popup/menu events

Writes use atomic replacement where appropriate. Corrupt state is preserved as a diagnostic backup before defaults are recovered. Removing a platform does not delete browser data. Clearing site data is separate, confirmed, and may affect related domains in the same profile.

## Provider development

Structured runs use `BuildProvider` and normalized events while preserving redacted provider payloads. Subscription status is checked through the installed client; Warden never reads its token files. API fallback is unavailable unless explicitly configured and each run is approved in the UI.

Read [architecture.md](architecture.md), [../docs/capability-matrix.md](../docs/capability-matrix.md), and [../SECURITY.md](../SECURITY.md).
