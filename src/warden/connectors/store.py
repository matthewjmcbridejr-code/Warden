"""Connected account store — server-side only, tokens never returned to callers."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .models import ConnectedAccount

_LOCK = Lock()

def _vault_root() -> Path:
    base = Path(os.getenv("WARDEN_CONNECTOR_VAULT_ROOT",
                          os.path.expanduser("~/.local/share/warden/connectors")))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _accounts_path() -> Path:
    return _vault_root() / "accounts.json"


def _load_accounts() -> list[dict]:
    path = _accounts_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _save_accounts(accounts: list[dict]) -> None:
    path = _accounts_path()
    path.write_text(json.dumps(accounts, indent=2))
    try:
        path.chmod(0o600)
    except Exception:
        pass


class ConnectorStore:
    def list_accounts(self, redact: bool = True) -> list[dict]:
        with _LOCK:
            accounts = _load_accounts()
        return [
            {k: ("[redacted]" if k in ("token_ref", "secret_ref", "refresh_token", "access_token") and redact else v)
             for k, v in acc.items()}
            for acc in accounts
        ]

    def get_account(self, account_id: str) -> dict | None:
        with _LOCK:
            for acc in _load_accounts():
                if acc.get("account_id") == account_id:
                    return acc
        return None

    def save_account(self, account: ConnectedAccount, token: str | None = None) -> dict:
        with _LOCK:
            accounts = _load_accounts()
            accounts = [a for a in accounts if a.get("account_id") != account.account_id]
            record = account.to_dict(redact=False)
            if token:
                record["token_ref"] = f"vault:{account.account_id}"
                self._store_token(account.account_id, token)
            accounts.insert(0, record)
            _save_accounts(accounts)
        return account.to_dict(redact=True)

    def disconnect_account(self, account_id: str) -> bool:
        with _LOCK:
            accounts = _load_accounts()
            before = len(accounts)
            accounts = [a for a in accounts if a.get("account_id") != account_id]
            if len(accounts) < before:
                _save_accounts(accounts)
                self._delete_token(account_id)
                return True
        return False

    def _store_token(self, account_id: str, token: str) -> None:
        token_file = _vault_root() / f"{account_id}.token"
        token_file.write_text(token)
        try:
            token_file.chmod(0o600)
        except Exception:
            pass

    def _get_token(self, account_id: str) -> str | None:
        token_file = _vault_root() / f"{account_id}.token"
        if token_file.exists():
            return token_file.read_text()
        return None

    def _delete_token(self, account_id: str) -> None:
        token_file = _vault_root() / f"{account_id}.token"
        try:
            token_file.unlink(missing_ok=True)
        except Exception:
            pass


def list_accounts(redact: bool = True) -> list[dict]:
    return ConnectorStore().list_accounts(redact=redact)
