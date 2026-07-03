"""Per-client bearer tokens for the Warden Brain MCP server.

Lets us issue a distinct, revocable token per external client (Claude
Desktop, Codex CLI, etc.) instead of sharing one static WARDEN_BRAIN_TOKEN
for everyone. Only the SHA-256 hash of each token is ever stored on disk —
the raw token is shown once at issue time and cannot be recovered later.

Storage: ~/.local/share/warden/mcp_clients/tokens.json (mode 0600), a JSON
list of client records:
  {client_id, name, token_hash, created_at, revoked_at, last_used_at}

This is intentionally simple (a JSON file + file lock), matching the
existing pattern in src/warden/connectors/store.py rather than introducing
a new storage layer.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional

_LOCK = Lock()


def _vault_root() -> Path:
    base = Path(
        os.getenv("WARDEN_MCP_CLIENTS_ROOT", os.path.expanduser("~/.local/share/warden/mcp_clients"))
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def _tokens_path() -> Path:
    return _vault_root() / "tokens.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _load() -> list[dict]:
    path = _tokens_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _save(records: list[dict]) -> None:
    path = _tokens_path()
    path.write_text(json.dumps(records, indent=2))
    try:
        path.chmod(0o600)
    except Exception:
        pass


def _redact(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "token_hash"}


def issue_token(name: str) -> tuple[str, str]:
    """Create a new client + token. Returns (client_id, raw_token).

    The raw_token is returned exactly once — only its hash is persisted.
    """
    client_id = uuid.uuid4().hex[:12]
    raw_token = secrets.token_urlsafe(32)
    record = {
        "client_id": client_id,
        "name": name,
        "token_hash": _hash_token(raw_token),
        "created_at": _now(),
        "revoked_at": None,
        "last_used_at": None,
    }
    with _LOCK:
        records = _load()
        records.append(record)
        _save(records)
    return client_id, raw_token


def list_clients(redact: bool = True) -> list[dict]:
    with _LOCK:
        records = _load()
    return [_redact(r) if redact else dict(r) for r in records]


def revoke_token(client_id: str) -> bool:
    """Mark a client's token revoked. Returns True if a matching client was found."""
    with _LOCK:
        records = _load()
        found = False
        for r in records:
            if r.get("client_id") == client_id and not r.get("revoked_at"):
                r["revoked_at"] = _now()
                found = True
        if found:
            _save(records)
    return found


def verify_token(raw_token: str) -> Optional[dict]:
    """Return the (redacted) client record if raw_token is valid and not revoked,
    else None. Updates last_used_at on success. Never raises."""
    if not raw_token:
        return None
    token_hash = _hash_token(raw_token)
    with _LOCK:
        records = _load()
        match = None
        for r in records:
            if r.get("token_hash") == token_hash and not r.get("revoked_at"):
                match = r
                break
        if match is not None:
            match["last_used_at"] = _now()
            _save(records)
    return _redact(match) if match else None


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Manage Warden Brain MCP client tokens")
    sub = parser.add_subparsers(dest="cmd", required=True)

    issue_p = sub.add_parser("issue", help="Issue a new client token")
    issue_p.add_argument("--name", required=True, help="Client name, e.g. 'claude_app' or 'codex_app'")

    sub.add_parser("list", help="List issued clients (tokens never shown)")

    revoke_p = sub.add_parser("revoke", help="Revoke a client's token")
    revoke_p.add_argument("client_id")

    args = parser.parse_args()

    if args.cmd == "issue":
        client_id, raw_token = issue_token(args.name)
        print(f"client_id: {client_id}")
        print(f"token (shown once, save it now): {raw_token}")
    elif args.cmd == "list":
        for rec in list_clients():
            status = "revoked" if rec.get("revoked_at") else "active"
            print(f"{rec['client_id']}  {rec['name']:<20} {status:<8} "
                  f"created={rec['created_at']} last_used={rec.get('last_used_at')}")
    elif args.cmd == "revoke":
        ok = revoke_token(args.client_id)
        print("revoked" if ok else f"no such client_id: {args.client_id}")


if __name__ == "__main__":
    _cli()
