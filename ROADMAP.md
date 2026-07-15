# Roadmap

Warden's near-term priority is reliability and proof, not a larger orchestration surface.

## Next

- Richer native diff, changed-file, test, artifact, and approval views.
- Provider protocol upgrades when official Claude, Gemini, and Grok clients expose approval/ACP channels suitable for Warden.
- Better background run notifications, recovery controls, and packaged-runtime diagnostics.
- Release coverage for additional Linux packaging formats and architectures.

## Later: HyperAgent Remote Build Worker

A future trusted Warden Extension may connect to a HyperAgent Remote Build Worker for explicit remote missions, webhook status, evidence return, and a public worker/MCP protocol. This is intentionally not implemented in 0.3.0. HyperAgent today is an ordinary untrusted Web Platform preset; its website receives no structured execution or Warden privilege.

Any worker design must define install trust, authentication ownership, repository isolation, approval semantics, cancellation, billing visibility, event provenance, proof verification, and failure recovery before it can ship.

## Not planned

- Importing or decrypting Chrome cookies.
- Extracting provider OAuth tokens.
- Silent API-key billing fallback.
- Restoring the legacy tmux prompt-injection runner as a desktop dependency.
