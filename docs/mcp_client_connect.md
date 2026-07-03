# Connecting external apps to Warden Brain MCP

The Warden Brain MCP server (`src/warden/brain_mcp_server.py`) runs as an
HTTP service on `127.0.0.1:8126` (`warden-brain-http` systemd unit), fronted
publicly by nginx+TLS at `https://mcp.mctable.online` and
`https://mcp.mctable.team`, exposing Warden Memory/search/recall tools at
`/mcp`. This doc covers connecting external apps: Codex App and Claude App
(Phase 1, per-client bearer tokens) and ChatGPT/Notion (Phase 2, full
OAuth 2.1).

## Phase 1: Codex App + Claude App (local apps, done now)

Both Claude Desktop and the Codex CLI run **on the same machine** as Warden,
so there's no need to expose anything publicly or build OAuth for this
phase — a per-client bearer token over loopback HTTP is sufficient and
simpler to operate/revoke.

### Why per-client tokens instead of the existing `WARDEN_BRAIN_TOKEN`

The server previously only supported one shared `WARDEN_BRAIN_TOKEN` env
var. `src/warden/mcp_tokens.py` adds a small token store
(`~/.local/share/warden/mcp_clients/tokens.json`, mode 0600) so each app
gets its own token:

- Only the SHA-256 hash of each token is ever persisted — the raw token is
  shown once at issue time and cannot be recovered later.
- Revoking one client (e.g. if a laptop is lost) doesn't affect others.
- `verify_token()` tracks `last_used_at` per client for basic auditing.
- The old `WARDEN_BRAIN_TOKEN` env var still works unchanged for backward
  compatibility. All three token kinds this server accepts — the legacy
  shared token, per-client tokens, and (Phase 2) OAuth-issued tokens — are
  now unified behind one check: `OAuthProvider.load_access_token()` in
  `src/warden/mcp_oauth.py`, which the SDK's own `RequireAuthMiddleware`
  calls to gate the `/mcp` route.

### Issue a token and connect

```bash
bash scripts/warden_mcp_client_connect.sh
```

This prompts for a client name (`claude_app`, `codex_app`, ...), issues a
token, and prints ready-to-paste config for both apps using the
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote) bridge (a small
stdio↔HTTP proxy that works with any MCP client version, since not every
Claude Desktop / Codex CLI release supports raw remote-HTTP MCP config
natively yet):

```json
{
  "mcpServers": {
    "warden-brain": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:8126/mcp", "--header", "Authorization:Bearer <token>"]
    }
  }
}
```

```toml
[mcp_servers.warden-brain]
command = "npx"
args = ["-y", "mcp-remote", "http://127.0.0.1:8126/mcp", "--header", "Authorization:Bearer <token>"]
```

If your installed client version does support a native remote-HTTP MCP
config (URL + headers directly, no bridge), you can point it at
`http://127.0.0.1:8126/mcp` with an `Authorization: Bearer <token>` header
directly instead.

### Managing tokens

```bash
# List issued clients (tokens are never shown again, only names/status)
PYTHONPATH='.:src' .venv/bin/python -m warden.mcp_tokens list

# Revoke a client
PYTHONPATH='.:src' .venv/bin/python -m warden.mcp_tokens revoke <client_id>
```

### What Codex/Claude get access to

Whatever tools `brain_mcp_server.py` already exposes — memory search/recall,
Warden status, watcher/session tools, WebStudio tools, etc. There's no
separate scoping per client yet (see Limitations) — every issued token has
the same access as the shared token did.

## Phase 2: ChatGPT connectors + Notion (built)

ChatGPT's connector platform and Notion's MCP integration both drive users
through a full OAuth 2.1 authorization-code + PKCE flow with dynamic client
registration (RFC 7591) — they don't take a manually-pasted token. This is
now implemented in `src/warden/mcp_oauth.py`, using the official `mcp`
Python SDK's built-in OAuth support (`mcp.server.auth`) rather than
hand-rolled protocol logic:

- `https://mcp.mctable.online/.well-known/oauth-authorization-server` —
  metadata discovery (issuer, authorize/token/register/revoke endpoints).
- `POST /register` — dynamic client registration. This is intentionally
  **open**, per spec — any app can self-register as a client (this is
  normal; it's how ChatGPT/Notion add a new MCP server without you manually
  creating credentials for them ahead of time).
- `GET /authorize` → our consent screen at `/oauth/consent` (see below) →
  redirects back to the client's `redirect_uri` with a short-lived,
  single-use authorization code.
- `POST /token` — exchanges the code (+ PKCE verifier) for an access token
  (1 hour) and refresh token (30 days, rotated on each use). Fully handled
  by the SDK — it verifies PKCE, expiry, and redirect-URI matching before
  ever calling into our code.
- `POST /revoke` — revokes an access or refresh token (and its paired
  token).

### The consent screen — this is the actual security boundary

Self-registration (`/register`) is open, but **authorizing** a code for a
registered client requires proving you're the account owner — otherwise
anyone on the internet who registers a client could mint themselves a
working token to your Warden Memory. `GET /oauth/consent?request_id=...`
renders a page showing the requesting app's name and scope, with a
passphrase field. Approving requires `MCP_OAUTH_OWNER_PASSPHRASE` (a env
var you set — separate from `WARDEN_BRAIN_TOKEN`, so the brain token itself
is never typed into a browser form). Wrong passphrase or an expired/unknown
request both deny without revealing which.

### Config

```bash
# Required for the OAuth flow to work at all — the consent screen won't
# approve anything without this set.
MCP_OAUTH_OWNER_PASSPHRASE=<choose a strong passphrase, keep it out of git>

# Defaults to https://mcp.mctable.online — override if you want ChatGPT/
# Notion to authenticate against a different public issuer URL.
MCP_OAUTH_ISSUER_URL=https://mcp.mctable.online
```

Set these in the same place `WARDEN_BRAIN_TOKEN` lives for the
`warden-brain-http` systemd unit (`/etc/systemd/system/warden-brain-http.service`'s
`EnvironmentFile`), then `sudo systemctl restart warden-brain-http`.

### Connecting ChatGPT / Notion

In each platform's "Add connector" / "Add MCP integration" flow, give it:
`https://mcp.mctable.online/mcp` as the server URL. The platform discovers
everything else (authorize/token/register endpoints) from
`/.well-known/oauth-authorization-server` automatically, self-registers,
and opens the `/authorize` consent page in a browser for you to approve.

Their exact redirect URIs/origins aren't known ahead of time — if either
platform's browser-based setup step hits a CORS rejection, add its origin
to the `allowed_origins` list in `TransportSecuritySettings` in
`brain_mcp_server.py` (currently includes `mcp.mctable.team`,
`mcp.mctable.online`, and `notion.so`/`www.notion.so` as a starting point).

### Token scope

Every OAuth-issued token has a single `"mcp"` scope — the same
all-or-nothing access model Phase 1's bearer tokens already use. Per-tool
scoping (e.g. distinguishing read vs. write tools) isn't implemented yet;
it's a natural follow-up once there's a concrete need for it.

## Safety notes

- Tokens are bearer secrets — treat them like passwords.
  `warden_mcp_client_connect.sh` never writes the raw Phase 1 token to disk
  or logs it; it's shown once in your terminal only. Same for OAuth-issued
  tokens — the SDK returns them once in the `/token` response body, never
  logged or persisted in plaintext (`src/warden/mcp_oauth.py` only ever
  stores SHA-256 hashes).
- `/register` being open is expected/by-design per the OAuth Dynamic Client
  Registration spec — it's `/authorize` (gated by
  `MCP_OAUTH_OWNER_PASSPHRASE`) that actually controls who gets a token.
- Revoke a Phase 1 per-client token immediately if a client machine is lost
  or a token leaks: `python -m warden.mcp_tokens revoke <client_id>`. For
  an OAuth-issued token, use `POST /revoke` (standard RFC 7009) or rotate
  `MCP_OAUTH_OWNER_PASSPHRASE` to stop approving new ones.
- Single-owner system: every OAuth token's `subject` is hardcoded to
  `"matt"` — this is not a multi-tenant auth server.
