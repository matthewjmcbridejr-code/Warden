# Warden Memory Style Guide

When recording or summarizing project memory, use this guide.

See also: `docs/warden_memory_examples.md`

---

## Purpose

Warden Memory records operational facts that future agents can safely act on.
It is not a log, not a journal, and not a scratch pad.

Every record should answer: **"What does the next agent need to know to avoid repeating a mistake or redoing proven work?"**

---

## Memory Types (kind field)

| Kind | Use for |
|---|---|
| `decision` | An explicit choice made by the operator or agent — architecture, approach, naming |
| `proof` | A claim backed by a passing test, CI result, or observed command output |
| `failure` | A broken path, failed command, or approach that was abandoned with reason |
| `constraint` | A rule or limit that must not be violated (env gates, deploy rules, secrets) |
| `handoff` | End-of-session summary: what was done, what is next, what is fragile |
| `claim` | An unverified assertion — use when proof is not yet available |
| `test_result` | Output from a specific test run (pass/fail + command + scope) |
| `fragile_file` | A file or path that breaks easily or requires special care |
| `user_note` | Explicit operator instruction that overrides agent defaults |
| `fact` | A stable project fact unlikely to change (repo layout, service port, model name) |

**Do not use `claim` when you have evidence. Use `proof` or `test_result` instead.**

---

## Required Fields

Every memory submitted to Warden must include:

```json
{
  "title": "Short operational title (≤80 chars)",
  "summary": "One or two plain sentences of operational fact.",
  "kind": "<kind from table above>",
  "scope": "<project name>",
  "project_id": "<project name>",
  "repo_path": "<absolute path to repo root>",
  "source_ref": "<run://run_id | commit:<sha> | pr:<number> | test:<file::name> | manual>",
  "tags": ["<kind>", "<area>"],
  "status": "active"
}
```

Optional but recommended:

```json
{
  "agent_id": "codex_cli | claude_code_cli | captain | operator",
  "branch": "feat/example",
  "task_id": "plan_id or step_id if from captain"
}
```

---

## Status Values

| Status | Meaning |
|---|---|
| `active` | Current truth — used in context packs |
| `superseded` | Replaced by a newer record; reference the replacement |
| `stale` | Possibly still true but not recently verified |
| `forgotten` | Excluded from recall; remains auditable on disk |

**Do not leave old records as `active` when they are no longer true. Supersede them.**

---

## Evidence Rules

Evidence is what separates `proof` from `claim`.

Acceptable evidence (in order of strength):

1. Passing test command + output (`pytest -q tests/test_X.py` → `1 passed`)
2. Git commit SHA or PR number
3. Observed API response (status + key field)
4. Passing `git diff --check` or `node --check`
5. Operator-witnessed manual run with output captured

Not acceptable as evidence:

- "Agent said it passed"
- "Looks correct"
- "Should work"
- Large pasted log with no summary
- Screenshot description without the command

**If you do not have evidence, use `claim` status and set `status: "active"` until proven.**

---

## Redaction Rules

Never record any of the following:

- API keys, tokens, bearer values
- `.env` file contents
- Private key blocks (PEM, SSH)
- Passwords, cookies, auth headers
- GitHub personal access tokens
- Session IDs from external services

Warden backend redacts before storage and before context pack output.
Do not rely on backend redaction as permission to submit secrets — never submit them intentionally.

If a command output contains a token, summarize the result instead of pasting the raw output.

---

## Size Rules

Keep each memory compact enough to inject into a prompt without overflowing.

| Field | Limit |
|---|---|
| `title` | ≤80 characters |
| `summary` | ≤4 sentences |
| Total record | Aim for ≤600 characters of readable text |

Do not paste:

- Full stack traces (summarize to one sentence + error name)
- Full test output (record pass/fail count + test file)
- Full git diffs (reference commit SHA)
- Full API responses (record the key field and status code)

---

## Context Pack Writing Style

Context packs are injected before the agent's task prompt. They must be:

- **Scannable** — the agent reads it in under 5 seconds
- **Actionable** — every entry tells the agent what to do or avoid
- **Bounded** — no more than 8 records, 6000 characters total (Warden default)
- **Scoped** — only records matching the current project and repo path

Write summaries in present tense, active voice:

```
✓ "Private runner requires BOTH env flags set to true."
✗ "It was found that the runner needed flags to be set."
```

Reference the source when it is not obvious:

```
✓ "[m-proof-abc] Memory tests pass (pytest, 2026-06-20): run://run_xyz"
✗ "[m-proof-abc] Memory tests pass."
```

---

## Handoff Memory Pattern

At the end of a session, write one `handoff` memory with:

- What was completed (with evidence reference)
- What is still in progress or blocked
- The single safest next action
- Any fragile state the next agent should know about

Keep it to 8 bullet points or fewer. If it requires more, split into a `handoff` + `constraint` record.

---

## Canonical Record Shape (Markdown Reference)

```md
# <Short operational title>

## Type
decision | proof | failure | constraint | handoff | claim | test_result | fragile_file | user_note

## Scope
Project: <project_id>
Repo: <repo_path>
Branch: <branch>
Agent: <agent_id>
Run: <source_ref>

## Status
proven | claimed | active | stale | superseded | blocked

## Summary
One or two plain sentences of operational fact.

## Evidence
- Command: <exact command run>
- Result: <pass/fail + key output line>
- File: <file path if relevant>
- PR/commit: <sha or PR number>

## Why it matters
What the next agent should do differently because of this memory.

## Next action
The safest next useful action.

## Do not do
- List of actions to avoid.
```

---

## Anti-Patterns

| Anti-pattern | Why it fails |
|---|---|
| `"Fixed the bug"` as summary | No evidence, no scope, no actionable content |
| Storing raw command output | Too large for prompt injection; not ranked by relevance |
| Using `proof` kind with no evidence | Misleads future agents into trusting unverified state |
| One giant `handoff` for everything | Fails context pack ranking; split by kind |
| `status: "active"` on a superseded record | Pollutes context pack with stale truth |
| `source_ref: null` on a proof record | Makes the evidence untraceable |
| Repeating the repo path in every sentence | Wastes context pack characters |
| Tagging everything `["important"]` | Destroys ranking signal; use specific kind tags |

---

## Quick Reference: When to Write a Memory

| Situation | Kind | Status |
|---|---|---|
| Architecture choice made | `decision` | `active` |
| Test suite passed | `test_result` | `active` |
| Command proven to work | `proof` | `active` |
| Approach failed with reason | `failure` | `active` |
| Hard rule that must not be broken | `constraint` | `active` |
| End of session summary | `handoff` | `active` |
| Belief not yet verified | `claim` | `active` |
| File that breaks on innocent edits | `fragile_file` | `active` |
| Operator instruction | `user_note` | `active` |
