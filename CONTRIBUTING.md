# Contributing to Warden

Thanks for helping make Warden safer and more useful. Keep changes focused, preserve local-first behavior, and describe capabilities exactly as they work.

## Desktop setup

Requirements: Linux, Node.js 22+, npm, a C/C++ toolchain for `node-pty`, and the libraries required by Electron.

```bash
git clone https://github.com/matthewjmcbridejr-code/Warden.git
cd Warden/desktop
npm ci
npm run check
npm run dev
```

Build a Debian package without publishing:

```bash
npm run package:deb
dpkg-deb --info dist-electron/warden-ai-desk_*.deb
```

Desktop code lives in `desktop/src/main`, `desktop/src/preload`, `desktop/src/renderer`, and `desktop/src/shared`; tests live in `desktop/tests`.

## Add a platform preset safely

Presets in `desktop/src/main/web-platforms.ts` are ordinary editable `PlatformPreset` data. Add HTTPS first-party/authentication domains narrowly, add validation tests, and verify popup/navigation behavior. A preset must never receive privileged preload, IPC, filesystem, terminal, Brain, token, or cookie access. Do not create a structured provider merely because a site has a Build category.

## Structured provider boundary

Implement `BuildProvider` in `desktop/src/main/build-provider.ts` (or the appropriate existing adapter module), preserve raw redacted metadata, report capabilities honestly, and keep official client authentication in the official client. Never silently switch from subscription entitlement to API-key billing. An adapter without a tested approval channel must report `approvals: false`.

## Tests and verification

```bash
cd desktop
npm run typecheck
npm test
npm run build
```

For older Warden services:

```bash
cd ..
python -m pytest tests --ignore=tests/e2e --ignore=tests/browser -q
```

Run focused tests first, then the complete relevant suite. UI changes require a real screenshot or GUI smoke check in addition to compilation.

## Pull requests

- Work on a feature branch; do not rewrite shared history.
- Keep generated dependencies, packages, browser profiles, runs, and credentials out of Git.
- Include the problem, boundary decisions, proof commands/results, screenshots for visible changes, and remaining limitations.
- Do not claim provider execution, authentication, approvals, Brain saves, or package behavior that was not actually exercised.
- Follow [SECURITY.md](SECURITY.md) for private vulnerability reports.

Apache-2.0 applies to contributions accepted into this repository.
