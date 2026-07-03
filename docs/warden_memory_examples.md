# Warden Memory Examples

Reference examples for each memory kind. Use these as templates.

See also: `docs/warden_memory_style.md`

---

## decision

```json
{
  "title": "Private runner gates required for memory injection",
  "summary": "Memory context is only injected into the Codex prompt when BOTH MCHARNESS_TMUX_RUNNER_ENABLED and MCHARNESS_CODEX_RUNNER_ENABLED are true. This is intentional — memory never enables an otherwise disabled runner.",
  "kind": "decision",
  "scope": "Warden",
  "project_id": "Warden",
  "repo_path": "/path/to/repo",
  "source_ref": "example:commit-sha",
  "tags": ["decision", "private-runner", "memory"],
  "status": "active",
  "agent_id": "operator",
  "branch": "feat/warden-memory-v1"
}
```

---

## proof

```json
{
  "title": "Memory test suite passes on isolated tmp root",
  "summary": "All 10 tests in tests/test_warden_memory.py pass with MCHARNESS_DATA_ROOT=/tmp/warden-test. Covers ID generation, scope isolation, redaction, context pack ranking, and fail-open dispatch.",
  "kind": "proof",
  "scope": "Warden",
  "project_id": "Warden",
  "repo_path": "/path/to/repo",
  "source_ref": "test:tests/test_warden_memory.py",
  "tags": ["proof", "test", "memory"],
  "status": "active",
  "agent_id": "codex_cli",
  "branch": "feat/warden-memory-v1"
}
```

---

## failure

```json
{
  "title": "Context pack unbounded — exceeded 32k chars in stress test",
  "summary": "Initial context pack builder had no character cap. With 200 active records it returned 34k chars, exceeding safe prompt injection size. Fixed by capping at max_chars=6000 and max_memories=8.",
  "kind": "failure",
  "scope": "Warden",
  "project_id": "Warden",
  "repo_path": "/path/to/repo",
  "source_ref": "example:commit-sha",
  "tags": ["failure", "memory", "context-pack"],
  "status": "active"
}
```

---

## constraint

```json
{
  "title": "Public service returns 403 on all memory routes",
  "summary": "The public McHarness service on port 8124 must return 403 for all /api/mcharness/memory/* routes. Memory is private-runner-only. Do not add a public fallback or proxy.",
  "kind": "constraint",
  "scope": "Warden",
  "project_id": "Warden",
  "repo_path": "/path/to/repo",
  "source_ref": "example:commit-sha",
  "tags": ["constraint", "security", "memory", "private-runner"],
  "status": "active"
}
```

---

## handoff

```json
{
  "title": "Memory v1 merged — next: proof/failure capture from completed runs",
  "summary": "Warden Memory v1 is merged to master. Storage, search, recall, context pack, and private Codex prompt injection are all working and tested. The cockpit memory panel is live on the private runner path.",
  "kind": "handoff",
  "scope": "Warden",
  "project_id": "Warden",
  "repo_path": "/path/to/repo",
  "source_ref": "example:commit-sha",
  "tags": ["handoff", "memory", "v1"],
  "status": "active",
  "notes": "Next: add explicit proof/failure/handoff capture from completed private runs. Jules and Grok injection paths not yet real. Supersede/forget API not yet implemented."
}
```

---

## claim

```json
{
  "title": "Claude Code CLI lane drop-in compatible with Codex lane shape",
  "summary": "Believed that adding claude_code_cli as a runner lane requires ~35 lines in api.py following the codex_cli pattern. Not yet implemented or tested.",
  "kind": "claim",
  "scope": "Warden",
  "project_id": "Warden",
  "repo_path": "/path/to/repo",
  "source_ref": "manual",
  "tags": ["claim", "claude-code", "runner-lane"],
  "status": "active"
}
```

**When the claim is proven, supersede this record with a `proof` or `decision` kind.**

---

## test_result

```json
{
  "title": "test_runner_sessions: all 10 pass after RUNNER_SESSION_PREFIX refactor",
  "summary": "pytest tests/test_runner_sessions.py -x -q: 10 passed, 0 failed. Session prefix is mch_run_, blocked names enforced, stale classification works.",
  "kind": "test_result",
  "scope": "Warden",
  "project_id": "Warden",
  "repo_path": "/path/to/repo",
  "source_ref": "test:tests/test_runner_sessions.py",
  "tags": ["test_result", "runner-sessions", "proof"],
  "status": "active",
  "branch": "feat/marius-resident-core"
}
```

---

## fragile_file

```json
{
  "title": "web/warden/app.js: runner-intent UI breaks if lane_id keys change",
  "summary": "app.js hardcodes lane_id strings (codex_cli, agy_cli, manual_paste) for dry-run preview rendering. If AGENT_LANES entries are renamed in api.py without updating app.js, the intent panel silently shows wrong commands.",
  "kind": "fragile_file",
  "scope": "Warden",
  "project_id": "Warden",
  "repo_path": "/path/to/repo",
  "source_ref": "manual",
  "tags": ["fragile_file", "frontend", "runner-lane"],
  "status": "active"
}
```

---

## API call pattern

To write any of the above via the private Warden Memory API:

```bash
curl -sS http://127.0.0.1:8125/api/mcharness/memories \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "...",
    "summary": "...",
    "kind": "proof",
    "scope": "Warden",
    "project_id": "Warden",
    "repo_path": "/path/to/repo",
    "source_ref": "example:commit-sha",
    "tags": ["proof", "memory"],
    "status": "active"
  }'
```

The private runner path (port 8125) is required. Port 8124 returns 403.
