# Warden Memory

Warden Memory is a Pieces-inspired, project-scoped memory layer for Warden-controlled agent work. It is not broad OS surveillance.

Its job is to preserve useful project truth between Codex, Captain, Jules, Grok, and future Warden agent runs: decisions, failures, proof, constraints, fragile files, acceptance tests, and handoff context.

> Warden Memory is Pieces-inspired but project-scoped. It is not broad OS surveillance.

## Scope

Warden Memory captures only records explicitly submitted through Warden workflows or APIs. Records live under the configured Warden workbench data root.

It may capture:

- project and repository facts
- user notes and decisions
- bounded agent prompts and results
- failed or blocked attempts
- test and proof summaries
- safety constraints
- fragile files and acceptance tests
- handoff and next-step summaries

It does not capture:

- clipboard contents
- screenshots or audio
- browser or shell history
- cookies or authentication data
- arbitrary files
- home-directory activity
- background filesystem events

Do not import broad Pieces OS history into Warden Memory until a separate, explicit, reviewed import policy exists.

## Record Model

Records are JSON-compatible and backward-compatible with the original Warden note shape.

```json
{
  "memory_id": "m-private-runner-abc123",
  "scope": "Warden",
  "project_id": "Warden",
  "repo_path": "/path/to/legacy-warden",
  "title": "Private runner constraint",
  "summary": "Memory context is injected only after private runner gates pass.",
  "source": "warden",
  "source_ref": "run://run_123",
  "tags": ["constraint", "private-runner"],
  "kind": "constraint",
  "status": "active",
  "confidence": 1.0,
  "branch": "feat/warden-memory-context-pack-v1",
  "task_id": null,
  "agent_id": "codex_cli",
  "metadata": {},
  "compacted": true,
  "notes": null,
  "created_at": "2026-06-20T00:00:00Z",
  "updated_at": "2026-06-20T00:00:00Z"
}
```

Supported kinds:

`fact`, `decision`, `failure`, `blocked_attempt`, `proof`, `claim`, `handoff`, `constraint`, `test_result`, `agent_prompt`, `agent_result`, `user_note`, `repo_context`, `fragile_file`, and `acceptance_test`.

Supported statuses:

`active`, `superseded`, `stale`, and `forgotten`.

Context packs use only active records. Forgotten records remain auditable on disk but are excluded from recall.

## Redaction

Warden redacts likely secrets before writing a record and again before rendering a context pack. This includes provider keys, GitHub tokens, bearer authorization values, passwords, cookies, and private-key blocks.

Example:

```text
OPENAI_API_KEY=[REDACTED]
Authorization: Bearer [REDACTED]
password=[REDACTED]
[REDACTED PRIVATE KEY BLOCK]
```

Redaction is a safety layer, not permission to submit secrets. Operators and agents should never intentionally place credentials in memory.

## Project Isolation

Every context request includes a `project_id`. Recall includes only records whose `scope` or `project_id` matches, or whose stored `repo_path` exactly matches the request metadata.

The `repo_path` field is treated as metadata. The context endpoint does not read the path or inspect files supplied by the caller.

## Context Pack

The context builder ranks active, matching records by explicit kind priority, prompt keyword overlap, agent/task/branch match, and recency. Ordering is deterministic and bounded by both record count and character count.

Example:

```md
# Warden Memory Context

## Project / Repo
- Project: Warden
- Repo: /path/to/legacy-warden
- Branch: feat/example

## Relevant Decisions
- [m-decision-123] Private memory: Keep memory behind private runner gates.

## Prior Failures / Avoid
- [m-failure-456] Unbounded output: Cap context records and characters.

## Proven State
- [m-proof-789] Memory tests: Isolated pytest coverage passed.

## Source Memories
- m-decision-123: Private memory
- m-failure-456: Unbounded output
- m-proof-789: Memory tests
```

The response contract is:

```json
{
  "context": "# Warden Memory Context\n...",
  "memory_count": 3,
  "memory_ids": ["m-decision-123", "m-failure-456", "m-proof-789"],
  "truncated": false,
  "scope": "Warden"
}
```

If no relevant memory exists, `context` is empty and `memory_count` is zero.

## Prompt Injection

On the private Codex runner path, Warden builds memory context only after runner flags and the allowlisted repository are validated. When context exists, the dispatched prompt is:

```md
# Warden Memory Context

...

---

# User Task

<original prompt, unchanged>
```

If context is empty or memory storage is unavailable, Warden dispatches the original prompt unchanged. Memory is fail-open for agent availability. It never enables an otherwise disabled runner.

The public service cannot read, search, create, recall, or render Warden Memory through the McHarness memory routes.

## API

All routes below are private-runner-only:

- `GET /api/mcharness/memory/health`
- `GET /api/mcharness/memories`
- `GET /api/mcharness/memories/search?q=...&scope=...`
- `GET /api/mcharness/memories/recall?q=...&scope=...`
- `POST /api/mcharness/memories`
- `POST /api/mcharness/memories/remember`
- `POST /api/mcharness/memory/remember`
- `POST /api/mcharness/memory/recall`
- `POST /api/mcharness/memory/context-pack`

Example:

```bash
curl -sS http://127.0.0.1:8125/api/mcharness/memory/context-pack \
  -H 'Content-Type: application/json' \
  -d '{
    "project_id": "Warden",
    "repo_path": "/path/to/legacy-warden",
    "agent": "codex_cli",
    "prompt": "Fix the memory panel",
    "branch": "feat/example",
    "max_memories": 8,
    "max_chars": 6000
  }'
```

The public service on port 8124 returns `403` for these memory routes. Existing public/private runner enablement flags, ports, and deployment behavior are unchanged.

## Cockpit UI

The Warden cockpit exposes Memory as a top-level section with:

- private-only availability and memory count
- recent project memories
- scoped search
- a bounded Remember Note form
- a Context Pack Preview for Codex, Jules, Grok, and Captain

The preview is inspect-only and never launches an agent. The existing Codex launch modal shows that memory context will be attached when available; backend injection remains authoritative.

When memory routes return `403` or are unavailable, the cockpit shows `Memory is private-runner-only` and disables search, write, and preview controls. It does not request memory through a public fallback.

Visible memory strings are defensively redacted in the browser before rendering, even though the backend also redacts storage and output.

## Operator Workflow

1. Remember a decision, failure, constraint, proof result, or handoff.
2. Search project memory before repeating work.
3. Preview the context pack for the next agent task.
4. Launch Codex or Captain with memory attached by the private runner.
5. Store proof, failure, or handoff context from the completed run.

## Tests

`tests/test_warden_memory.py` uses an isolated temporary workbench root and covers:

- generated IDs and compatibility fields
- search and scope isolation
- redaction before storage and output
- deterministic, bounded context packs
- prompt preservation and fail-open behavior
- private-only API access
- no arbitrary filesystem reads
- private Codex dispatch prompt injection

`tests/browser/warden-cockpit.spec.js` covers:

- recent memory rendering and frontend redaction
- scoped search
- manual remember submission
- context-pack preview
- public-service disabled controls

Run:

```bash
PYTHONPATH="$PWD" python -m pytest -q tests/test_warden_memory.py
```

## Known Limitations

- Recall is keyword/tag/recency based; there is no vector database.
- Warden does not automatically summarize every run transcript.
- Run-result memory capture remains explicit; raw agent output is never promoted to proof automatically.
- Jules and Grok launch adapters are not implemented in this repository, so prompt injection currently targets the existing private Codex launch path.

## Next Steps

- Add explicit proof/failure/handoff capture from completed private runs.
- Add supersede/forget APIs with audit history.
- Add a small private-only context preview panel.
- Add adapter-level prompt injection when Jules and Grok execution paths become real and gated.
