# Security policy

## Supported release

Security fixes are prepared on the active desktop release branch. Until a signed/tagged release is published, build from a reviewed commit and verify the locally produced checksum.

## Report a vulnerability

Do not open a public issue for a vulnerability that could expose credentials, provider sessions, local files, Brain data, or arbitrary execution. Use GitHub's private vulnerability reporting for this repository. Include the affected version, platform, reproduction, expected boundary, and whether any provider or local data may have been exposed. Never attach real cookies, OAuth tokens, passwords, API keys, or private prompts.

## Desktop trust boundaries

Warden distinguishes three capability levels:

1. **Web Platform:** untrusted remote content in a sandboxed `WebContentsView`.
2. **Structured Provider:** an explicit adapter to an official local client or protocol.
3. **Warden Extension:** a separately installed trusted adapter.

Adding a website does not create a Structured Provider or Extension.

Remote content has no Warden preload, Node.js integration, privileged IPC, terminal, filesystem, Brain, token, or cookie API. Context isolation, sandboxing, web security, certificate checks, URL policy, and deny-by-default permissions remain enabled. Warden rejects `file:`, `javascript:`, `data:`, and privileged local/internal navigation. Localhost HTTP is permitted only in explicit development mode.

OAuth popups use the originating named Warden partition and the same locked-down preferences. Unknown domains require a visible native decision. Warden never logs URL query strings, authorization headers, cookies, passwords, tokens, or remote console contents.

## Authentication and billing

Official provider clients own login, token storage, and refresh. Warden does not extract, copy, store, or manipulate provider OAuth tokens. Subscription execution removes API credential variables from the child environment. API-key execution is opt-in, visibly labeled, and requires per-run approval; it is never a silent fallback.

## Local data

Browser sessions, project paths, redacted prompts/events, terminal history, evidence, and proof can still be sensitive. They live in the current OS user's Electron application-data directory with owner-only files where Warden writes records. Protect the account and disk accordingly. See [docs/privacy.md](docs/privacy.md).

## Public repository hygiene

Do not commit `.env` files, credentials, Electron profile data, run stores, browser databases, screenshots of real conversations, or generated `desktop/dist*`/`node_modules` output. Pull requests should pass the documented secret scan and tracked-file audit.
