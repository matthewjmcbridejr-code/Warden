# Command Deck Reconciliation Handoff

## Canonical repo

`/home/matt/workspaces/warden/mcharness-public-export`

This is the active Warden working repo used for reconciliation. The scratch/source repo was not treated as canonical.

## Source repo used for UI

`/home/matt/Documents/Warden`

Copied/ported from source:

- `web/warden/command-deck.html`
- `web/warden/command-deck.css`
- `web/warden/command-deck.js`
- Command Deck topbar link in `web/warden/index.html`
- Command Deck static/API tests, adjusted for the active repo backend shape

## Branch

`feat/marius-resident-core`

The target repo was already on this feature branch with existing uncommitted Warden/Marius work. No branch switch was performed.

## Commit

Pending at handoff creation. Expected commit message:

`chore(warden): reconcile command deck ui into working repo`

## Runtime/service finding

`systemctl cat mcharness-cockpit-private.service` and `systemctl cat mcharness-cockpit.service` returned no unit content in this environment.

Running process inspection showed:

- Active target-repo uvicorn on `127.0.0.1:6969`:
  `.venv/bin/python -m uvicorn src.warden.app:app --host 127.0.0.1 --port 6969 --log-level warning`
- Warden Brain MCP processes from the target repo on local ports/stdio.
- No public Warden service was restarted.

Runtime proof was done with a temporary private uvicorn on `127.0.0.1:8125` using:

- `MCHARNESS_DATA_ROOT=/tmp/warden-runtime-proof`
- `WARDEN_BOARD_ROOT=/tmp/warden-runtime-board`
- no systemd restart
- no public deploy

## Backend preservation

The active repo already had Claude's richer Command Deck backend in `src/warden/api.py`, including:

- state/proofs/relay/events/demo-seed endpoints
- task create/claim/proof/failure/handoff/dispatch endpoints
- daily brief endpoint nearby

Codex did not replace that backend with the scratch implementation. The UI was adapted to consume the active backend shape (`tasks` + `summary`) and still supports the older `columns` shape defensively.

## Board root fix

Hard-coded private board path was removed from the committed Command Deck-related modules. A separate untracked `src/warden/brain_mcp_server.py` in this dirty worktree also had the same local edit but was not part of this reconciliation commit.

Current default pattern uses:

```python
WARDEN_BOARD_ROOT -> MCTABLE_BOARD_ROOT -> ~/.local/share/warden/board
```

Updated files:

- `src/warden/api.py`
- `src/warden/agent_dispatcher.py`
- `src/warden/daily_brief.py`

## Verification

Passed:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/warden-pycache PYTHONPATH='.:src' .venv/bin/python -m py_compile src/warden/api.py src/warden/risk_gate.py src/warden/agent_dispatcher.py src/warden/daily_brief.py tests/test_warden_command_deck.py tests/test_warden_cockpit_static.py
node --check web/warden/command-deck.js
timeout 90s env PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/warden-pycache MCHARNESS_DATA_ROOT=/tmp/warden-reconcile-test PYTHONPATH='.:src' .venv/bin/pytest -q tests/test_warden_command_deck.py tests/test_warden_cockpit_static.py tests/test_warden_risk_gate.py tests/test_warden_agent_dispatcher.py tests/test_warden_daily_brief.py
```

Pytest result:

```text
35 passed, 1 warning in 0.72s
```

The warning was only pytest cache write failure because the sandbox cannot write `.pytest_cache` in the target repo.

## API proof

Against temporary private server on `127.0.0.1:8125`:

```text
page: 200
state-before: 200
proofs: 200
relay: 200
events: 200
seed: 201
state-after: 200
```

JSON excerpts:

```text
state-before: ok=true, task_count=0, queued=0, proof_needed=0
seed: ok=true, title="Demo Mission", status="queued", agent="codex", tags=["demo"]
state-after: ok=true, task_count=1, queued=1
```

## Browser proof

In-app browser loaded:

`http://127.0.0.1:8125/web/warden/command-deck.html`

Verified:

- H1: `Warden Command Deck`
- Subtitle includes: `Local-first AI workforce control plane`
- agent lanes visible
- mission board visible
- proof ledger visible
- relay timeline visible
- brain/context panel visible
- `Run Demo Mission` button visible
- clicking demo seed shows seeded `Demo Mission` cards
- deck mode displays `Demo Data`

Screenshot:

`/tmp/warden-command-deck-proof-final.png`

## Known notes

- The active repo still had unrelated dirty work before this reconciliation. Do not assume every dirty file belongs to this task.
- The public service was not restarted or deployed.
- The temporary uvicorn used for proof was stopped after browser capture.
- Existing target TestClient-based static tests previously hung under the installed FastAPI/Starlette stack, so focused Command Deck/static tests now avoid TestClient. Runtime HTTP proof is covered by uvicorn + curl.

## Next recommended step

Claude should review the staged/committed diff and decide whether to split broader pre-existing Warden backend changes into a separate commit if needed. Do not deploy publicly until the active repo commit is reviewed.
