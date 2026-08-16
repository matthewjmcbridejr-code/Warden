# Warden MCP 2.0 & A2A Interoperability Architecture

## Executive Overview

Warden MCP 2.0 establishes Warden as a local-first control plane and persistent interoperability layer connecting human intent, autonomous agents, foundation models, context, and project state.

### The Central Boundary Rule

```
MCP      = Capabilities, Context, Tools, Resources, Data
A2A      = Remote Agents, Task Delegation, Agent Cards, Messages
Captain  = Orchestration, Policy, Reconciliation, Bounded Planning
Warden   = Authoritative State (Tasks, Claims, Runs, Artifacts, Decisions, Memory)
```

---

## 1. Model Context Protocol (MCP) Integration

Warden uses MCP to expose tools, resources, and context to AI assistants and IDE environments.

- **Tools (`tools/list`)**: Executable operations (e.g. `warden_bootstrap`, `warden_context_delta`, `warden_ground_claim`, `warden_board`).
- **Resources (`resources/list`, `resources/read`)**: Structured data blobs and artifacts accessible via `warden://` URIs:
  - `warden://artifacts/{artifact_id}`: Immutable execution outputs, diffs, reports, and test results.
  - `warden://claims/{claim_id}`: Epistemic claims and grounding evidence.
  - `warden://runs/{run_id}`: Execution envelope reports.
- **Catalog Revision Stability**: The `tool_catalog_revision` hash changes **only** when served tool schema or capability surfaces change, ensuring predictable client caching.

---

## 2. Agent-to-Agent (A2A) Protocol Integration

Warden implements A2A interoperability allowing Warden to act as:
1. An **A2A Server**: Exposing a valid Agent Card at `/.well-known/agent.json` and `/api/mcharness/a2a/agent-card`.
2. An **A2A Client**: Discovering and delegating work to remote A2A-compliant agents.
3. A **Normalized Agent Registry**: Aggregating local agents (`claude`, `agy`, `codex`, `marius`, `spark`) and external A2A agents into a single queryable registry.

### A2A Agent Card Specification (`/.well-known/agent.json`)

```json
{
  "name": "Warden Captain Orchestrator",
  "description": "Local-first AI control plane for task orchestration, context reconciliation, and multi-agent coordination.",
  "version": "2.0.0",
  "protocol": "a2a",
  "capabilities": [
    "task.orchestration",
    "context.reconciliation",
    "code.review",
    "grounding.verification"
  ],
  "accepted_task_types": [
    "software_architecture",
    "code_implementation",
    "reconciliation",
    "audit"
  ],
  "input_modalities": ["text/plain", "application/json"],
  "output_modalities": ["application/json", "text/markdown"],
  "endpoint": "http://127.0.0.1:6969/api/mcharness/a2a/tasks",
  "authentication_mode": "oauth2",
  "provider": "Warden Core"
}
```

---

## 3. Delegation & Task Mapping

Remote A2A tasks map directly into existing Warden task and run state without creating parallel storage:

```
A2A Task Request → Warden Task ID → Warden Run Envelope → Execution → Artifacts → Grounded Claims → Proof
```

All remote task updates emit internal Warden state events monitored by the Captain reconciler and rendered in Captain Desk.
