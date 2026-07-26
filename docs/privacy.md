# Privacy and local data

Warden AI Desk is local-first, but local does not mean non-sensitive. Provider sessions, project paths, prompts, run events, terminal history, diffs, and proof can reveal private work.

## What Warden stores

Electron normally uses `~/.config/Warden AI Desk/` on Linux. The exact location follows Electron's `app.getPath('userData')` for the current OS account.

| Data | Purpose | Notes |
|---|---|---|
| Desktop state | Restore projects, platform definitions, profiles, layout, execution mode, and terminal metadata | Corrupt input is copied before recovery |
| Chromium partitions | Keep website logins for named Warden profiles | Never imported from Chrome; never shared across profile partitions |
| Run records | Resume structured work and display redacted events, auth source, approvals, and evidence | Provider metadata is retained only after redaction |
| Terminal history | Restore a private per-terminal command list | Terminal processes themselves do not survive restart |
| Diagnostics | Diagnose navigation, popup, permission, download, and native-menu flows | Host/protocol/fingerprints only; no URL query, headers, credentials, or remote console text |
| Handoffs/proof | Continue or review work and prove outcomes | Brain saving is optional and reports unavailable/failed honestly |

## Authentication ownership

Website sessions remain in their selected Warden Chromium profile. Structured provider authentication remains inside `codex`, `claude`, `gemini`, or `grok`. Warden does not extract, copy, store, refresh, or manipulate provider OAuth tokens.

Subscription launches remove common API-key variables from the child environment. API-key execution is a separately selected fallback with a per-run billing warning.

## Clearing and removal

Removing a platform only removes its definition and keeps it restorable; it does not delete browser data. “Clear this site's data” is a separately confirmed troubleshooting action. Electron/Chromium storage can use registrable-domain scope, so related sites assigned to the same named profile may also be signed out. Warden does not promise isolation it cannot guarantee.

To erase all Warden desktop state, first quit the application, back up anything needed, and remove the Warden user-data directory manually. This is intentionally not a one-click in-app operation.

## Private Brain

When the private Warden Brain service is reachable, Save proof sends a concise proof record to that explicitly configured local service. When unavailable, Warden saves local proof and labels Brain as unavailable or failed; it never fakes a remote save.

## Public issue hygiene

Before sharing logs or screenshots, remove project paths, prompts, provider content, run/thread IDs, email addresses, and account identifiers. Never upload Chromium profile directories or credential files.
