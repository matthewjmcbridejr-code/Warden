# Connecting agents to Warden

Any MCP client gets Warden's full tool surface — shared memory, task board,
handoffs, brain vault, Captain planning, connected mail accounts, and the
configured upstream MCP services — through one command:

```bash
warden mcp
```

Every authenticated remote client must call `warden_bootstrap` before using a
connected service. The call is valid with no arguments during cold start. Its
response includes caller identity, fresh constraints and decisions, existing
tasks/claims, proof expectations, and a live credential-free service catalog.
The catalog tells the agent which upstreams are reachable, which tools Warden
exposes, and which mail account IDs are actually operational. Service calls
fail closed with a pointer back to `warden_bootstrap` until that handshake
succeeds, so the protocol does not depend on an agent remembering a prompt
convention.

Bootstrap follows the authenticated bearer token across stateless HTTP
transports because hosted clients such as Gemini Spark may open a fresh MCP
transport for later tool calls in one run. A new or refreshed access token must
bootstrap again.

OAuth activity is attributed as `<client-name>:<client-id-prefix>`. Separate
Hyperagent, Spark, Claude, or other registrations therefore remain distinct
even when they all act for the same Warden operator; no bearer value is exposed
in context or memory records.

That runs the Warden Brain MCP server on stdio. For agents on the **same
machine** (the normal case), no tokens, no ports, no config files beyond the
client's own MCP registration. Remote/HTTP access is the advanced path at the
bottom.

## Claude Code

```bash
claude mcp add warden -- warden mcp
```

## Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "warden": {
      "command": "warden",
      "args": ["mcp"]
    }
  }
}
```

If Claude Desktop can't find `warden` on its PATH, use the absolute path to
the console script (e.g. `/path/to/Warden/.venv/bin/warden`).

## Cursor

Add to `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "warden": {
      "command": "warden",
      "args": ["mcp"]
    }
  }
}
```

## Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.warden]
command = "warden"
args = ["mcp"]
```

## Verify the connection

Ask the agent to call `warden_health` — it should report memory counts and
session info. `warden_me` returns the operator profile; `warden_mcp_hub_status`
shows whether external hub tools are proxied in. `warden_service_catalog`
returns the combined Warden-native, mail-account, and upstream inventory with
redacted live readiness and policy-blocked counts.

---

## Advanced: remote access over HTTP

Everything below is only needed when the agent runs on a **different machine**
than Warden (e.g. a phone app, ChatGPT connectors, a hosted service). Run the
HTTP server:

```bash
python -m warden.brain_mcp_server --http --port 8126
```

HTTP mode refuses to start without auth configured. Two options:

### Per-client bearer tokens (simplest)

```bash
bash scripts/warden_mcp_client_connect.sh
```

Issues a named, individually revocable token (only its SHA-256 hash is stored,
in `~/.local/share/warden/mcp_clients/tokens.json`) and prints ready-to-paste
config using the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote)
stdio↔HTTP bridge:

```json
{
  "mcpServers": {
    "warden": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://your-host/mcp", "--header", "Authorization:Bearer <token>"]
    }
  }
}
```

Clients that support native remote-HTTP MCP config can point at the URL with an
`Authorization: Bearer <token>` header directly, no bridge.

Manage tokens:

```bash
python -m warden.mcp_tokens list      # names/status only — raw tokens are never shown again
python -m warden.mcp_tokens revoke <client_id>
```

### OAuth 2.1 (ChatGPT connectors, Notion, Hyperagent, …)

Platforms that drive a full OAuth flow (dynamic client registration + PKCE)
work out of the box — give them `https://your-host/mcp` as the server URL and
they discover everything else from `/.well-known/oauth-authorization-server`.

The security boundary is the **consent screen**: approving a client requires
the passphrase in the `MCP_OAUTH_OWNER_PASSPHRASE` env var on the server.
Without it set, no OAuth client can ever be approved. Set it (plus optionally
`MCP_OAUTH_ISSUER_URL`) in the environment of whatever runs the HTTP server,
then restart.

Notes:

- Open `/register` is by design (RFC 7591) — registration grants nothing;
  `/authorize` + passphrase is what mints tokens.
- Access tokens last 1 hour; refresh tokens 30 days, rotated on use; revoke
  via standard `POST /revoke`.
- All tokens share a single `"mcp"` scope today — per-tool scoping is a
  planned hardening phase.
- Front the HTTP port with TLS (nginx or similar) before exposing it beyond
  localhost. Treat every token like a password.

## Connected services and accounts

External agents authenticate to Warden, not separately to every provider.
Connect Gmail, Outlook, or iCloud once in Warden Settings. Agents then call
`warden_mail_accounts_status`, choose the intended `account_id`, and use the
read-only search/read tools. Multiple mailboxes can coexist; raw provider
credentials never appear in MCP responses. Live checks for multiple accounts
run concurrently, so adding more Google/iCloud accounts does not multiply the
agent's bootstrap delay by one provider timeout per account.

Warden also discovers the existing McTable gateway. Its default public policy
registers only the known read-only McTable, GitHub, and research tools; direct
filesystem access, browser control, process execution, repository mutation,
and destructive memory tools are omitted. Context7 is mounted as a separate
built-in read-only upstream with stable tool names:

- `context7_resolve_library_id`
- `context7_query_docs`

Context7 works anonymously by default. Set `CONTEXT7_API_KEY` in the Warden
Brain service environment to use an operator-owned key, or set
`WARDEN_CONTEXT7_ENABLED=0` to disable it.

Additional remote MCP services can be mounted without changing code by setting
`WARDEN_MCP_EXTRA_UPSTREAMS_JSON` to a list. Keep credentials in separate
environment variables and refer to those names with `header_env`; never put a
secret directly in the JSON value. Example:

```json
[
  {
    "name": "internal-docs",
    "url": "https://docs.example.com/mcp",
    "prefix": "docs",
    "header_env": {"Authorization": "INTERNAL_DOCS_AUTH"},
    "allow_tools": ["search-docs", "read-doc"]
  }
]
```

Hyperagent can be mounted as a read-only upstream after completing its OAuth
browser sign-in on a trusted operator workstation. Store the resulting bearer
token in the private `/etc/warden-hyperagent.env` EnvironmentFile (never in
git), then set the extra-upstream list to the review-only tools:

```json
[
  {
    "name": "hyperagent",
    "url": "https://hyperagent.com/api/mcp",
    "prefix": "hyperagent",
    "header_env": {"Authorization": "HYPERAGENT_AUTHORIZATION"},
    "allow_tools": [
      "list_agents",
      "list_threads",
      "get_thread",
      "list_pending_approvals"
    ]
  }
]
```

Use the least-privilege Hyperagent scopes `threads:read` and
`approvals:read` (plus `offline_access` when refresh is required). Keep
`create_thread`, `send_message`, and `resolve_approval` out of `allow_tools`.
The hub's default `read_only` policy also blocks every unlisted third-party
tool.

Unknown third-party tools are not exposed unless named in that upstream's
`allow_tools` list. For a reviewed exception on the McTable gateway, set
`WARDEN_MCP_HUB_ALLOW_TOOLS` to a comma-separated list of exact tool names.
`WARDEN_MCP_HUB_POLICY=all` exists only as an explicit operator override and
restores the entire upstream surface, including mutating tools.

Every upstream is isolated at startup. If one service is down, Warden keeps its
native tools and any other healthy upstreams available. Use
`warden_mcp_hub_status` for a credential-free reachability, exposed-tool, and
policy-blocked-tool view.
