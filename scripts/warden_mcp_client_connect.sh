#!/usr/bin/env bash
# Issue a per-client bearer token for the Warden Brain MCP server and print
# ready-to-paste config for that client (Claude Desktop / Codex CLI / other).
#
# The raw token is shown exactly once, on this terminal, and is never written
# to a file by this script or logged anywhere. Save it immediately.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "Warden Brain MCP — client connect"
echo "----------------------------------"
echo "This issues a distinct, revocable token for one external client (Claude"
echo "Desktop, Codex CLI, etc.) so each app can be granted/revoked independently"
echo "instead of sharing one server-wide secret."
echo

read -r -p "Client name (e.g. claude_app, codex_app): " CLIENT_NAME
if [ -z "$CLIENT_NAME" ]; then
  echo "No name entered — aborting." >&2
  exit 1
fi

OUT="$(PYTHONPATH=".:src" .venv/bin/python -m warden.mcp_tokens issue --name "$CLIENT_NAME")"
CLIENT_ID="$(echo "$OUT" | sed -n 's/^client_id: //p')"
RAW_TOKEN="$(echo "$OUT" | sed -n 's/^token (shown once, save it now): //p')"

echo
echo "Issued client_id: $CLIENT_ID"
echo "Token (SAVE THIS NOW — it will not be shown again):"
echo "  $RAW_TOKEN"
echo
echo "MCP server URL: http://127.0.0.1:8126/mcp"
echo
echo "--- Claude Desktop config snippet (~/.config/Claude/claude_desktop_config.json) ---"
cat <<EOF
{
  "mcpServers": {
    "warden-brain": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:8126/mcp", "--header", "Authorization:Bearer $RAW_TOKEN"]
    }
  }
}
EOF
echo
echo "--- Codex CLI config snippet (~/.codex/config.toml) ---"
cat <<EOF
[mcp_servers.warden-brain]
command = "npx"
args = ["-y", "mcp-remote", "http://127.0.0.1:8126/mcp", "--header", "Authorization:Bearer $RAW_TOKEN"]
EOF
echo
echo "(Both clients connect via the 'mcp-remote' bridge, which speaks stdio to"
echo " the app and forwards to our HTTP+Bearer server — this works regardless"
echo " of whether your installed client version supports raw remote-HTTP MCP"
echo " config natively. If yours does, you can point it directly at the URL"
echo " above with an Authorization: Bearer header instead.)"
echo
echo "Next commands:"
echo "  List issued clients:   PYTHONPATH='.:src' .venv/bin/python -m warden.mcp_tokens list"
echo "  Revoke a client:       PYTHONPATH='.:src' .venv/bin/python -m warden.mcp_tokens revoke $CLIENT_ID"
