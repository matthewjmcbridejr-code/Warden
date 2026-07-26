# Warden AI Desk troubleshooting

## A provider page is blank or offline

Use the three-dot native menu to reload or open the current platform in the system browser. Check network/DNS and the status message in Warden. Warden does not disable certificate validation or web security to bypass provider failures.

## OAuth Next appears to do nothing

Current builds surface popup/redirect decisions and keep OAuth windows visible in the originating named profile. If a domain is new, choose Allow once, Trust for this platform, Open in system browser, or Cancel. A decision prompt may be behind another application window; switch back to Warden. Safe diagnostics are stored under the Warden user-data directory at `diagnostics/platform-events.jsonl`.

Do not work around authentication with `--disable-web-security`, `--no-sandbox`, Chrome-cookie copying, or certificate bypass flags.

## The platform menu is clipped

0.3.0 uses an Electron native menu rather than renderer HTML, because remote `WebContentsView` content is a separate native surface. If clipping persists, record the window size, desktop environment, and Electron version from About Warden.

## Structured provider is disconnected

Authenticate in the official local client, then use Refresh in Build:

```bash
codex login
claude        # follow the official Claude Code sign-in flow
gemini        # follow the Google-account sign-in flow
grok login
```

Warden reports installed/not authenticated, unknown entitlement, unsupported, or disconnected separately. It will not silently switch to API billing.

## Gemini reports unknown or unsupported entitlement

Gemini CLI and Code Assist entitlement behavior changes across client versions. Confirm the installed official CLI can run interactively with the desired Google account. If its machine-readable probe no longer supports the account type, Warden blocks structured dispatch rather than guessing.

## A terminal is stopped after restart

Expected: terminal metadata and history restore, but the PTY process does not. Select the stopped tab and choose Restart.

## State recovered from corruption

Warden preserves a timestamped copy of invalid desktop state and starts from safe defaults. The warning contains the backup location. Do not post that file publicly without reviewing it for project/platform information.

## Brain proof says unavailable

Local proof was still written. The optional private Brain service must be running at the configured local endpoint. Warden does not treat an unavailable or rejected Brain request as success.

## Package will not launch because of sandbox/AppArmor policy

Install the `.deb` normally and confirm your distribution supports Electron's Chromium sandbox. Do not permanently add `--no-sandbox`. Include the distribution, kernel, AppArmor message, and package version in a bug report.
