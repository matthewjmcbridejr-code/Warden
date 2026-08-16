# Warden MCP 2.0 Context Economy Architecture

## Overview

Warden Context Economy optimizes agent context consumption by treating state synchronization like **Git revision control**:
- **First Contact**: Initial compact cold start (< 2 KB). Receive `context_revision`, `tool_catalog_revision`, `profile_revision`.
- **Warm Reconnect**: Provide known revisions (`known_context_revision`, etc.). On zero changes, return tiny reconnect confirmation (< 300-400 bytes).
- **Targeted Retrieval**: Fetch specific decisions, claims, docs, or artifacts on-demand instead of re-downloading whole repositories.
- **Artifact-First Delivery**: Large tool outputs (> 8 KB) are stored as immutable `ArtifactRef`s and returned as lightweight summaries + URIs.

## Revisions & Protocol

### 1. Context Revision (`context_revision`)
- **Format**: `ctx_<hash>`
- **Scope**: Project-scoped (`project="warden"`).
- **Determinism**: Only updates when project decisions, constraints, tasks, or claims change. Irrelevant project or volatile timestamp updates do NOT churn revision.

### 2. Operator Profile Revision (`profile_revision`)
- **Format**: `prof_<hash>`
- **Scope**: Material operator preferences, priorities, and contact details.
- **Determinism**: Stable across sessions until material operator priorities change.

### 3. Tool Catalog Revision (`tool_catalog_revision`)
- **Format**: `cat_rev_<hash>`
- **Scope**: Served native tools + upstream hub tools.
- **Delta Sync**: Connected clients compare `revision_hash`. If unchanged, tool definition lists are omitted.

## Context Budget Caps (`ContextBudget`)

| Metric | Target Cap | Description |
|---|---|---|
| `bootstrap_max_bytes` | 2,500 B | Compact cold start payload ceiling |
| `delta_max_bytes` | 1,500 B | Context delta update ceiling |
| `retrieved_memories_max` | 3 | Default on-demand recall limit |
| `retrieved_docs_max` | 3 | Default doc search limit |
| `inline_tool_result_max_bytes` | 8,000 B | Max inline output before converting to `ArtifactRef` |
