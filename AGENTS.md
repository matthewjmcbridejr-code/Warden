# Warden contributor guide

Warden is a local-first AI workspace. The Electron desktop is the recommended
entry point for new users; the Python services and browser-memory components
are optional advanced surfaces.

## Working rules

- Treat this repository as the source of truth.
- Preserve unrelated local changes and never rewrite shared Git history.
- Never commit credentials, `.env` files, browser profiles, run stores,
  generated packages, or local Brain data.
- Keep remote websites sandboxed: no Node integration, Warden preload,
  privileged IPC, filesystem, terminal, token, or Brain access.
- Keep website authentication and official local Build-client authentication
  separate. Never copy provider tokens or silently switch to API billing.
- Require an explicit operator decision before agent work reaches a project.
- Keep private Brain, mail, browser-memory, and server integrations optional.
- Document capabilities as they actually work and include verification proof.

## Repository map

```text
desktop/            Electron AI Desk, packaging, and Vitest suite
src/warden/         Python Warden services and optional Brain/connectors
src/marius/         Optional local resident assistant and provider gateway
web/warden/         Legacy Python-service web interface
browser-extension/  Optional local browser-memory extension
docs/               Architecture, privacy, setup, and contributor notes
tests/              Python tests and browser/e2e suites
```

## Verification

For desktop changes:

```bash
cd desktop
npm ci
npm run check
```

For Python changes, use a repository-local virtual environment:

```bash
PYTHONPATH="$PWD:$PWD/src" .venv/bin/python -m pytest \
  tests --ignore=tests/e2e --ignore=tests/browser -q
```

Before publication:

```bash
bash scripts/public_release_audit.sh
```

That audit requires `gitleaks`. Visible UI changes also require an installed or
packaged GUI smoke check under Electron's normal Chromium sandbox.

## Data boundaries

Fresh installations must not assume the repository author's identity, paths,
accounts, services, or private data. Operator context belongs in ignored local
storage and environment configuration. The optional browser extension can
capture sensitive browsing and typed content; it must be enabled only by an
informed operator on a profile they intend to index.
