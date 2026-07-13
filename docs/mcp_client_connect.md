# Connecting agents to Warden

Any MCP client gets Warden's full tool surface — shared memory, task board,
handoffs, brain vault, Captain planning — through one command:

```bash
warden mcp
```

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
shows whether external hub tools are proxied in.

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
