# Warden Project

## Identity

Warden is the control and execution layer for supervised AI work.

This repository contains the public Warden AI Desk plus earlier Python services that provide agent-facing MCP, memory, task/handoff, connector, proof, and control-room capabilities.

## Product boundaries

- Public repository code and documentation must remain safe for public release.
- Private operator context, client mappings, credentials, connector state, and personal project registry do not belong in this repository.
- Warden may expose local and hosted capabilities, but agents should interact through explicit audited interfaces rather than direct database access.
- Production-changing actions require explicit operator authorization.

## Source of truth

- Repository implementation: Git.
- Standing agent rules: `AGENTS.md`.
- Current implementation snapshot: `docs/CURRENT-STATE.md`.
- Machine-readable project identity: `.warden/project.yaml`.
- Detailed architecture: existing architecture and security documentation in `docs/`.

## Context contract

For substantial work, an agent should read:

1. `AGENTS.md`
2. `docs/PROJECT.md`
3. `docs/CURRENT-STATE.md`
4. The task-specific file or issue
5. Relevant architecture/security docs for the affected subsystem

Runtime verification and Git state override stale documentation when they conflict.
