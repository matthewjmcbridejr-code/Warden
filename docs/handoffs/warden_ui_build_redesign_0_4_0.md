# Warden AI Desk 0.4.0 — project-centered UI redesign

Date: 2026-07-16
Branch: `feat/warden-ai-desk`

## Outcome

Warden's primary Build experience is now a project command center instead of a prompt beside a technical log. The redesign combines the calm neutral canvas of the selected Monochrome Iris direction with Aubergine Alloy's warmer plum/copper identity, then carries that system across Chat chrome, Build, terminals, dialogs, onboarding, and repository screenshots.

## Build workflow

- Persistent project command bar with repository, branch/path, safe-workspace state, terminal access, and New mission action.
- Mission queue scoped to the selected project and persisted active-run selection.
- Outcome plus optional **Ready for review when** criteria; criteria become part of the real provider prompt.
- Explicit Codex subscription/provider readiness before launch.
- Four-phase Brief → Build → Verify → Review progress with normalized live activity.
- Interrupt-style approval card with allow, deny, and raw-request inspection.
- Evidence inspector for summary, changed files and diff, checks, proof history, provider-review handoff, and honest Brain save state.
- Existing isolated worktree safety remains authoritative: Apply to project, Request changes, Discard worktree, and reversible Undo.
- Build hides irrelevant Web Platform navigation; Chat still restores the full platform surface.

## Visual system

- Sora variable for interface hierarchy and Epilogue variable for Warden identity and major moments.
- Fonts are bundled offline in the application archive with their OFL licenses; no Google Fonts request is made at runtime.
- Graphite/black work surfaces; copper for primary intent and brand; plum for selected state; violet for active/focus state; semantic green/amber/red for evidence and decisions.
- The xterm palette, BrowserWindow/popup background, Developer Build, auth state, native-adjacent Chat toolbar, and every dialog use the same tokens.

The font decision follows Simon Cozens' 2026 assessment that current generative Latin type systems still struggle with vectorization, spacing, kerning, and completeness. Warden therefore uses production open fonts rather than making daily-work legibility depend on an experimental generated face: https://simoncozens.github.io/state-of-ai-font-generation/

## Product research applied

- OpenAI's Codex app describes project-organized durable tasks, parallel work, worktree isolation, and in-thread diff review: https://openai.com/index/introducing-the-codex-app/
- OpenAI's long-running-work guide emphasizes strong, verifiable goals and the artifact side panel as the place where work is inspected and reviewed: https://cdn.openai.com/pdf/8a9f00cf-d379-4e20-b06f-dd7ba5196a11/OAI_WhitePaper_Codex-maxxing26.pdf
- OpenAI's internal Codex guide recommends issue-shaped prompts, Ask/plan before large changes, persistent AGENTS.md context, and a task queue as a lightweight backlog: https://cdn.openai.com/pdf/6a2631dc-783e-479b-b1a4-af0cfbd38630/how-openai-uses-codex.pdf
- GitHub Desktop and VS Code both make changed-file selection and focused diff review first-class, which informed Warden's right-hand evidence inspector.

## Automated proof

```text
npm run package:deb
TypeScript: passed
Vitest: 16 files, 73 tests passed
Production build: passed
Debian package: passed

Package: warden-ai-desk
Version: 0.4.0
Architecture: amd64
Installed-Size: 329758 KiB
Artifact: desktop/dist-electron/warden-ai-desk_0.4.0_amd64.deb
SHA-256: 2b4f1f88b7724c7e84e88573208803c9267770c49cfb3d8b4df3d4afafdd53da
sha256sum --check: OK
```

New focused tests cover mission/evidence structure, review criteria entering the real run prompt, safe/context execution preservation, handoff/proof wiring, active-run restoration, project-first navigation, offline font packaging, palette retirement, and terminal integration.

## Visual proof

- Compiled production CSS/HTML exercised at 1600×960 for both new-mission and active-mission states.
- Compact verification at the supported 1024×700 minimum measured document `scrollWidth=1024` and `scrollHeight=700`; the mission and evidence surfaces remained inside the viewport with no clipping.
- Chat chrome and the platform dialog were visually inspected at 1440×900.
- Public screenshots contain synthetic project/provider data only and were replaced with the 0.4.0 visual system.

## Runtime boundary

This host cannot run the newly unpacked Electron binary with Chromium's normal sandbox because its generated `chrome-sandbox` is not root-owned/setuid and AppArmor restricts the unprivileged-user-namespace fallback. Warden was not launched with `--no-sandbox`, and no system security setting was weakened. Final installed-binary interaction therefore requires installing the `.deb` normally and launching it as the desktop application.

The UI sprint did not require a billable provider run or provider login. Existing provider/security boundaries were preserved. Unrelated `web/warden/fonts/` and `web/warden/noise.png` changes were not modified or staged.
