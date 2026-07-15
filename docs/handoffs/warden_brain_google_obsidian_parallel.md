# Warden Brain — Local + Google Parallel Implementation

**Date:** 2026-06-30  
**Branch:** feat/marius-resident-core  
**Commit:** 9e8384c

## What Was Built

### Local Brain (free, default)
- `src/warden/brain/` — full subpackage
  - `vault.py` — Obsidian-compatible Markdown vault (8 folders, no Obsidian app required)
  - `index.py` — SQLite FTS5 index at `~/.warden/brain/brain.sqlite3`
  - `local_provider.py` — search + extractive answering with keyword fallback
  - `google_provider.py` — Discovery Engine provider (env-configurable, ADC or key file)
  - `hybrid.py` — parallel fanout, merge, dedup, graceful Google fallback
  - `mirror.py` — local→Google one-way mirror with checksum-based skip
  - `models.py` — BrainSource, BrainChunk, BrainCitation, BrainAnswer

### Google Brain (optional)
- Wired to existing **example-codebase** Discovery Engine data store
- Engine: `mctable-search`, serving config: `default_search`
- Uses Application Default Credentials (ADC) — no service account key needed
- Config in `~/.config/warden/cloud_keys.env` (no secrets, only project IDs)
- APIs enabled: `discoveryengine`, `gmail`, `storage`, `cloudresourcemanager`, `iamcredentials`

### API Endpoints (14 new)
```
GET  /warden/brain/health
GET  /warden/brain/providers
POST /warden/brain/init-vault
POST /warden/brain/reindex
GET  /warden/brain/sources
GET  /warden/brain/search?q=...
POST /warden/brain/ask
POST /warden/brain/write-note
POST /warden/brain/google/mirror
GET  /warden/brain/google/mirror-status
GET  /warden/brain/google/status
POST /warden/brain/google/verify
```

### MCP Tools (10 new in brain_mcp_server.py)
`brain_status`, `brain_init_vault`, `brain_reindex`, `brain_list_sources`,
`brain_search`, `brain_ask`, `brain_write_note`,
`brain_google_status`, `brain_google_mirror`, `brain_mirror_status`

## Next Steps

### Gmail OAuth (BLOCKED on manual step)
Matt needs to enter credentials through Warden UI:
1. Open http://127.0.0.1:6969/web/warden/app.html
2. Settings → Account Connectors → Gmail → "Set up Gmail connection"
3. Enter Client ID and Client Secret from Google Console OAuth client
4. Click "Save and activate"
5. Click "Sign in with Google"

OAuth client setup in Google Console:
- Name: Warden Local Gmail Connector
- Authorized origins: `http://127.0.0.1:6969`, `http://localhost:6969`  
- Redirect URIs: `http://127.0.0.1:6969/api/mcharness/warden/connectors/gmail/callback`

### Google Brain — Mirror local vault
After Warden Brain is indexed:
```bash
curl -X POST http://127.0.0.1:6969/api/mcharness/warden/brain/google/mirror \
  -H "Content-Type: application/json" -d '{"dry_run": false, "limit": 50}'
```

### Tests
- 68 brain tests, all passing (fully mocked, no network)
- 466 unit tests total, all passing
- 9/9 e2e tests passing (1 flaky on slow Captain API, passes on retry)

## Security
- No secrets in any committed file
- Google credentials: env vars only, never in API responses
- iCloud passwords: vault only, cleared from DOM after submit
- OAuth tokens: vault only (`~/.local/share/warden/connectors/`)
- Mirror: secrets redacted from Markdown before push to Google
