# Reusable Warden Agent Execution Guidelines (Context Economy)

## Guidelines for Token-Efficient Agent Sessions

1. **Bootstrap Once**: Call `warden_bootstrap(mode="auto")` exactly once at session startup.
2. **Record Revisions**: Save `context_revision`, `tool_catalog_revision`, and `profile_revision`.
3. **Use Revision-Aware Reconnects**: On subsequent reconnects, pass `known_context_revision`, `known_tool_catalog_revision`, and `known_profile_revision`.
4. **Use Context Delta**: Use `warden_context_delta(since_revision=...)` after startup to query scoped updates.
5. **Targeted Retrieval**: Retrieve only specific decisions, memories, or docs required for the immediate step.
6. **Artifact-First Protocol**: Accept `ArtifactRef` URIs for large test outputs, diffs, or logs rather than requesting giant inline payloads.
7. **Focused Verification**: Run targeted unit tests during implementation; execute full test suites only at final merge gates.
8. **Compact Status Updates**: Keep progress messages concise (`DONE`, `NEXT`, `BLOCKER`).
9. **Checkpoint Continuity**: Resume from `RunEnvelope` / checkpoint state rather than re-orienting from scratch.
