# Warden AI Desk release checklist

This checklist prepares a release; it does not authorize publishing.

## Product and security

- [ ] About shows the intended semantic version and architecture.
- [ ] First-run onboarding, empty/loading/error/auth states, project/profile context, custom platform flow, native overflow, destructive confirmations, and keyboard focus were visually inspected.
- [ ] Remote platform preferences retain sandbox, context isolation, Node disabled, no preload, web security, URL policy, permission denial, and explicit popup/download behavior.
- [ ] Subscription auth source is visible and API-key fallback requires a per-run warning.
- [ ] Generated profiles, state, run data, packages, dependencies, and private screenshots are not tracked.
- [ ] Current-tree secret scan reports zero unreviewed findings; historical findings are classified without printing values.

## Verification

```bash
cd desktop
npm ci
npm run check
npm run package:deb
package="$(find dist-electron -maxdepth 1 -name 'warden-ai-desk_*_amd64.deb' -print -quit)"
dpkg-deb --info "$package"
package_dir="$(dirname "$package")"
package_name="$(basename "$package")"
(cd "$package_dir" && sha256sum "$package_name" > "$package_name.sha256")
```

- [ ] Normal-sandbox packaged runtime smoke passes without `--no-sandbox`.
- [ ] OAuth popup and native menu installed-style smoke passes.
- [ ] Structured Codex harmless run records events/approval/evidence and can resume.
- [ ] A disconnected/unsupported provider is represented honestly.
- [ ] README image/link check and tracked-file audit pass.
- [ ] Debian artifact checksum matches after copying to a clean directory.

## GitHub publishing (manual)

- [ ] Review focused commits and open a pull request from the feature branch.
- [ ] Wait for Desktop CI and Python CI.
- [ ] Merge only with explicit maintainer approval.
- [ ] Create annotated `vX.Y.Z` tag from the reviewed merge commit.
- [ ] Create GitHub Release notes from `CHANGELOG.md` and attach only the `.deb` plus `.sha256`.
- [ ] Verify the downloaded artifact checksum and install on a clean Debian/Ubuntu machine.

Ordinary branch CI builds artifacts for verification but never deploys or publishes a GitHub Release.
