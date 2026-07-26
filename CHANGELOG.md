# Changelog

All notable changes to Warden AI Desk are documented here. The desktop follows semantic versioning while it approaches a stable 1.0 contract.

## [Unreleased]

- No unreleased desktop changes recorded.

## [0.4.1] - 2026-07-26

### Added

- Added an independent-install guide covering Debian installation, source setup, website account sign-in, official Build-client authentication, local storage, updates, and troubleshooting.
- Clarified first-run onboarding so a new operator can use only their own accounts without Matt's private Warden services.

### Fixed

- Removed hard-coded owner identity from Brain MCP instructions, OAuth subjects, project bootstrap context, and the legacy memory identity card.
- Made connector credentials durable with private atomic writes, stable reconnect identifiers, backup recovery, and explicit credential status.
- Restored the legacy `warden up` documentation contract used by the Python suite while keeping AI Desk as the recommended desktop entry point.

## [0.4.0] - 2026-07-16

### Changed

- Rebuilt Simple Build as a project command center with a durable mission queue, outcome and review-criteria composer, provider/billing readiness, four-phase progress, visible approval interrupts, and a dedicated evidence inspector.
- Added native file, diff, check, proof, handoff, and Brain-save views to the primary Build workflow while preserving isolated worktrees and explicit Apply, Discard, and Undo decisions.
- Made Build visually project-first by hiding irrelevant Web Platform navigation while structured work is active and providing a direct terminal escape hatch.
- Replaced the olive visual system with the neutral **Monochrome Alloy** theme: calm graphite work surfaces, restrained aubergine/copper identity, semantic violet focus, and locally bundled Sora/Epilogue variable fonts.
- Rethemed Chat chrome, Developer Build, terminals, provider state, dialogs, onboarding, and public screenshots as one coherent desktop product.

### Verification

- Added focused workflow/theme tests for mission structure, review criteria, safe execution, handoffs, proof, offline fonts, terminal integration, and project-first navigation.
- Visually verified composer and active-run states at 1600×960 and the supported 1024×700 minimum with no page overflow or clipped review controls.

## [0.3.1] - 2026-07-14

### Fixed

- Wired Simple Build approvals, denial, technical details, cancellation, follow-up submission, and visible operation errors.
- Unified Simple and Developer Mode around the same active project and durable run, including project creation and restart restoration.
- Made **Keep changes** capture ordinary uncommitted, untracked, deleted, and agent-committed worktree changes as one synthesized commit without requiring repository Git identity.
- Made acceptance transactional through an abortable cherry-pick, guarded Discard against active runs, and persisted Undo as a separate revert commit with durable history.
- Replaced the dead read-only control with an honest transition to Developer Mode.

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

[Unreleased]: https://github.com/matthewjmcbridejr-code/Warden/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/matthewjmcbridejr-code/Warden/releases/tag/v0.4.1
[0.4.0]: https://github.com/matthewjmcbridejr-code/Warden/releases/tag/v0.4.0
[0.3.1]: https://github.com/matthewjmcbridejr-code/Warden/releases/tag/v0.3.1
[0.3.0]: https://github.com/matthewjmcbridejr-code/Warden/releases/tag/v0.3.0
