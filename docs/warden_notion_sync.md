# Warden Notion Sync Dry-Run

Warden Notion Sync v0 previews which local Warden board tasks would be promoted into a Notion inbox. It is intentionally dry-run first: it reads local task JSON, builds safe candidate payloads, detects duplicates, and returns a report without calling Notion.

## Endpoints

- `GET /api/mcharness/warden/notion/sync/status` reports whether dry-run is available and whether Notion-related environment variables are present, as booleans only.
- `POST /api/mcharness/warden/notion/sync/dry-run` reads the Warden board and returns `would_create` plus `would_skip` candidate lists.
- `POST /api/mcharness/warden/notion/sync/write` is blocked in v0. It returns a dry-run preview and does not write to Notion.

## Candidate Model

Each candidate includes:

- `warden_task_id`
- `title`
- `project`
- `status: candidate`
- `source: warden`
- `type: agent_task`
- `priority`
- `ai_summary`
- `proof_status`
- `agent`
- `repo_path`
- `branch`
- `created_at`
- `source_link`

## Proof Model

Proof status is derived from Warden task state:

- Completed or done tasks without proof are `proof_needed`.
- Tasks with `proof` or `proof_id` are `verified`.
- Failed tasks are `failed`.
- Tasks with an explicit blocker are `blocked`.
- Handoff tasks are `handoff`.

## Duplicate Detection

Candidates are skipped when they match an existing or earlier candidate by:

- `warden_task_id`, when present.
- Normalized `title + project + source`, when no task id is available.

## Run Locally

From the canonical Warden repo:

```bash
PYTHONPATH='.:src' .venv/bin/python -m py_compile src/warden/api.py src/warden/notion_sync.py tests/test_warden_notion_sync.py tests/test_warden_cockpit_static.py
node --check web/warden/command-deck.js
PYTHONPATH='.:src' .venv/bin/pytest -q tests/test_warden_notion_sync.py tests/test_warden_cockpit_static.py tests/test_warden_command_deck.py
```

## Seed and Preview

Use Command Deck demo seed, then preview sync:

```bash
curl -sS -X POST http://127.0.0.1:6969/api/mcharness/warden/command-deck/demo-seed   -H 'Content-Type: application/json'   -d '{"title":"Demo Mission","description":"Demonstrate Warden Command Deck dispatch loop.","agent":"codex","priority":"medium"}'

curl -sS -X POST http://127.0.0.1:6969/api/mcharness/warden/notion/sync/dry-run
```

## Safety

The status endpoint redacts secrets by design. It reports only true or false for `NOTION_API_KEY`, `NOTION_MASTER_INBOX_DATABASE_ID`, and `WARDEN_NOTION_WRITE_ENABLED`. Real Notion writes are not implemented in v0.

## Known Limitations

- No Notion API calls are made.
- Existing Notion rows are not queried yet; duplicate checks only use candidates supplied to the dry-run helper or duplicates within the local preview.
- `repo_path` is carried from local task metadata for operator clarity; portfolio/demo rendering should sanitize private absolute paths.
- The Command Deck panel previews candidate counts and proof status, but does not create Notion pages.
