# Warden AI Desk 0.3.1 — unified Simple Build handoff

Date: 2026-07-14
Branch: `feat/warden-ai-desk`

## Outcome

Claude's Phase 1 Simple Build surface is now connected to the same durable project and run state used by Developer Mode. The consumer loop no longer assumes that Codex creates Git commits: Warden captures the complete isolated worktree and applies it as one reviewable commit only after explicit acceptance.

## Product behavior

- Simple Build restores the active project and its saved active run after restart.
- Creating or selecting a project updates the shared project context used by both interface modes.
- Runs carry the stable project ID, and legacy runs without one are recovered by repository path.
- Allow once, deny, technical details, cancel, follow-up submission, Keep, Discard, and Undo are wired.
- Operation failures and safe-loop conflicts are visible in the Simple Build workspace.
- Unsafe/non-Git projects route to the real Developer Mode instead of a dead read-only control.
- Discard refuses active runs. Undo requires a clean project and is persisted as `undone` with its revert commit.

## Safe Git contract

1. Start from a clean project and record its commit.
2. Run Codex in an isolated `warden/task-*` worktree.
3. On **Keep changes**, stage the complete isolated tree, including uncommitted, untracked, deleted, and previously committed agent work.
4. Synthesize one commit parented to the recorded base using Warden's local non-personal commit identity.
5. Verify that the real project is still clean and at the recorded base.
6. Apply through `git cherry-pick`; abort on failure so the original project is restored.
7. Never push. Undo uses a new revert commit and never rewrites history.

## Proof

```text
npm run check
Typecheck: passed
Vitest: 15 files, 67 tests passed
Production build: passed

npm run package:deb
Debian package: desktop/dist-electron/warden-ai-desk_0.3.1_amd64.deb
SHA-256: b0f1f32ff7fa395e792c4c8cb8e280d06e3c393f0d683ca7d12a8659ce83625e
sha256sum --check: OK
Package metadata: warden-ai-desk 0.3.1, amd64
```

The focused Git tests exercise real temporary repositories and prove ordinary uncommitted edits, untracked files, project movement conflicts, no-change cleanup, missing Git identity, Discard isolation, reversible Undo, and dirty-project Undo refusal.

## Runtime boundary

The unpacked artifact could not complete the GUI smoke because this checkout's generated `chrome-sandbox` is owned by the unprivileged build user and this host disables the user-namespace fallback. Warden did not use `--no-sandbox`. The Debian post-install script configures `/opt/Warden AI Desk/chrome-sandbox` mode according to host user-namespace support. A final installed 0.3.1 GUI smoke therefore requires Matt to install the package with `sudo apt install` and launch it normally.

Unrelated `web/warden/fonts/` and `web/warden/noise.png` files were not changed or staged.
