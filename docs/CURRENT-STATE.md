# Warden Current State

Last reviewed: 2026-09-17

## Verified repository state

- The public repository's primary user-facing product is Warden AI Desk.
- The repository also retains earlier Python services under `src/warden/`.
- Existing Python architecture includes MCP, shared memory, task/handoff coordination, connectors/mail, proof gates, API/UI surfaces, and optional Notion integration.
- The historical private-service architecture is local-first and uses SQLite/local storage assumptions.
- The public repository intentionally excludes private operator data, credentials, browser/session data, and private Brain state.

## Hosted control-plane direction

A private hosted Warden control plane is being designed separately from the public repository's private operator data.

Target responsibilities include:

- project registry
- context assembly
- task and checkpoint state
- agent registry
- source registry
- permissions/policy metadata
- provenance and handoff metadata

The hosted design should reuse existing Warden domain concepts where they fit, while replacing workstation-local state assumptions with remotely available persistent services.

## Current deployment assumptions

Operator-reported hosted infrastructure currently includes:

- `warden-mcp-edge` on GCP
- `warden-worker` on GCP

Exact deployment configuration is not asserted by this public document and must be verified from the private environment before changes.

## Next control-plane milestone

1. Establish a private Warden HQ repository.
2. Define the canonical project/task/checkpoint schemas.
3. Register Warden and Phantom Signals as pilot projects.
4. Add deterministic context assembly behind the hosted MCP/API edge.
5. Keep persistent state outside any single workstation.
6. Validate identical project context from more than one device/client.

## Not yet established

The following must not be treated as implemented until verified:

- a canonical hosted project registry
- Firestore-backed Warden task/checkpoint state
- automatic GitHub/Notion/mail/Slack context retrieval
- universal agent onboarding through the hosted MCP edge
- semantic/vector retrieval for Warden HQ

These remain planned work.
