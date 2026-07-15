# Changelog

All notable changes to Warden AI Desk are documented here. The desktop follows semantic versioning while it approaches a stable 1.0 contract.

## [Unreleased]

- No unreleased desktop changes recorded.

## [0.3.0] - 2026-07-14

### Added

- Project-centered workspace restoration across repositories, profiles, platforms, Chat/Build layout, execution mode, terminals, and durable runs.
- Editable custom Web Platforms with ordinary HyperAgent, Perplexity, and Copilot presets; named persistent profiles; split view; restoration; and domain-trust management.
- Subscription-first Codex App Server, Claude Code, Gemini CLI, and Grok structured adapters with explicit capability/authentication reports.
- Durable normalized events, Codex approval bridge, cancellation/resume, context packs, evidence, handoffs, local proof, and optional private Brain proof saving.
- Secure visible OAuth popup flows and a native Chat overflow menu above provider `WebContentsView` surfaces.
- First-run onboarding, active project/profile context, About/version information, clearer empty/error/auth states, keyboard focus styling, and responsive desktop layout.

### Security

- Remote platforms remain sandboxed with no Warden preload, Node integration, privileged IPC, injected scripts, or direct local capability.
- API billing is never a silent subscription fallback.
- Public examples and documentation use synthetic paths/cloud identifiers; generated profiles, sessions, runs, packages, and dependencies remain ignored.

### Known limitations

- Codex is the only structured adapter with a Warden-controlled approval bridge.
- Packaging is release-proven for Debian/Ubuntu x86-64 only.

[Unreleased]: https://github.com/matthewjmcbridejr-code/Warden/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/matthewjmcbridejr-code/Warden/releases/tag/v0.3.0
