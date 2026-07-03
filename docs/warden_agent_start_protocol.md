# Warden Agent Start Protocol

Every agent operating in the Warden ecosystem **must** follow this protocol at the start of every session or task. No exceptions.

---

## Step 0 — Mandatory Bootstrap Check

Before reading or editing any file, call Workspace Authority:

```bash
curl -sS -X POST http://127.0.0.1:6969/api/mcharness/warden/workspaces/bootstrap \
  -H "Content-Type: application/json" \
  -d "{\"project_id\":\"warden\",\"task\":\"<your task here>\",\"cwd\":\"$(pwd)\"}" \
  | python -m json.tool
```

**If `safe_to_edit` is `false` or `warnings` is non-empty:**

1. **STOP. Do not make any edits.**
2. Note the `canonical_repo` from the response.
3. Switch to the canonical repo: `cd <canonical_repo>`
4. Re-run the bootstrap check.
5. Proceed only when `safe_to_edit: true` and `warnings: []`.

**Canonical repo for Warden:**
```
/home/matt/workspaces/warden/mcharness-public-export
```

**Do not code here (scratch/clones):**
```
/home/matt/Documents/Warden   ← scratch_or_clone — read-only reference only
```

---

## Step 1 — Verify Working Directory

```bash
pwd
git branch --show-current
git status --short
git log --oneline -3
```

Expected output must show:
- cwd = `/home/matt/workspaces/warden/mcharness-public-export`
- branch = `feat/marius-resident-core` (or an approved feature branch)
- no unexpected staged changes from other sessions

---

## Step 2 — Branch Policy

| Rule | Value |
|------|-------|
| Preserve main/master | **Yes** — never push directly to `main` |
| Prefer feature branches | **Yes** — `feat/<short-name>` |
| No force push | **Yes** — force-push is prohibited |
| No merge to main without review | **Yes** |

---

## Step 3 — No Secrets Rule

- Never read, print, log, or commit `.env*` files, credentials, tokens, or private keys.
- If a file path contains `secret`, `key`, `token`, `credential`, or `password` — skip it.
- If you need a secret, ask Matt explicitly. Do not infer or guess values.

---

## Step 4 — Do Your Work

- Edit only files in the canonical repo.
- Run compile/lint checks after every meaningful change:

```bash
PYTHONPATH='.:src' .venv/bin/python -m py_compile src/warden/api.py
node --check web/warden/command-deck.js
```

- Run the relevant test suite before calling work done:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH='.:src' .venv/bin/pytest -q \
  tests/test_warden_command_deck.py \
  tests/test_warden_cockpit_static.py \
  tests/test_warden_workspace_authority.py
```

---

## Step 5 — Proof Closeout (Mandatory)

Every task **must** end with one of:

| Kind | When to use |
|------|-------------|
| **proof** | Work completed and verified — include test results |
| **failure** | Blocked — include what failed and why |
| **decision** | Architectural choice made — include reasoning |
| **handoff** | Passing to next agent — include exact next action |

### Final Report Format

Return exactly this structure:

```
## Summary
<1-2 sentences>

## Files changed
<list>

## Tests run
<command + result>

## Runtime proof
<curl results or equivalent>

## Safety notes
<anything skipped or sensitive>

## Known blockers
<unresolved issues>

## Exact next action / Codex task
<precise instruction for the next agent>
```

---

## Quick Reference

```bash
# 1. Bootstrap check (MANDATORY)
curl -sS -X POST http://127.0.0.1:6969/api/mcharness/warden/workspaces/bootstrap \
  -H "Content-Type: application/json" \
  -d "{\"project_id\":\"warden\",\"cwd\":\"$(pwd)\"}" | python -m json.tool

# 2. Verify cwd
pwd && git branch --show-current && git status --short

# 3. Compile check
PYTHONPATH='.:src' .venv/bin/python -m py_compile src/warden/api.py
node --check web/warden/command-deck.js

# 4. Run tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH='.:src' .venv/bin/pytest -q \
  tests/test_warden_workspace_authority.py tests/test_warden_command_deck.py

# 5. Commit with Co-Authored-By
git commit -m "feat(warden): <description>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Enforcement

The Warden Agent Dispatcher enforces this protocol automatically:

- Every `dispatch_task()` call runs `_workspace_preflight()` before any command launches.
- If `safe_to_edit` is false, dispatch is **blocked** and a `workspace_drift_blocked` activity event is written to the board.
- No command template executes from a non-canonical worktree.
