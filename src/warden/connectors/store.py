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


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _vault_root() -> Path:
    base = Path(os.getenv("WARDEN_CONNECTOR_VAULT_ROOT",
                          os.path.expanduser("~/.local/share/warden/connectors")))
    _secure_directory(base)
    return base


def _accounts_path() -> Path:
    return _vault_root() / "accounts.json"


def _accounts_backup_path() -> Path:
    return _vault_root() / "accounts.json.backup"


def _read_account_list(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("connector account store must contain a list of objects")
    return data


def _load_accounts() -> list[dict]:
    path = _accounts_path()
    if not path.exists():
        return []
    try:
        return _read_account_list(path)
    except Exception:
        backup = _accounts_backup_path()
        try:
            return _read_account_list(backup)
        except Exception:
            return []


def _atomic_write_text(path: Path, value: str) -> None:
    """Durably replace a private vault file without exposing a partial write."""
    _secure_directory(path.parent)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        path.chmod(0o600)
    finally:
        temp_path.unlink(missing_ok=True)


def _save_accounts(accounts: list[dict]) -> None:
    path = _accounts_path()
    if path.exists():
        try:
            # Keep the last valid manifest so a corrupt/interrupted future write
            # cannot make every connector appear to vanish.
            current = _read_account_list(path)
            _atomic_write_text(_accounts_backup_path(), json.dumps(current, indent=2))
        except Exception:
            pass
    _atomic_write_text(path, json.dumps(accounts, indent=2))


def _account_key(account: dict) -> tuple[str, str]:
    return (
        str(account.get("provider", "")).strip().lower(),
        str(account.get("display_email", "")).strip().lower(),
    )


def _redact_account(account: dict) -> dict:
    redacted = {
        key: ("[redacted]" if key in (
            "token_ref", "secret_ref", "refresh_token", "access_token"
        ) else value)
        for key, value in account.items()
    }
    account_id = str(account.get("account_id", ""))
    redacted["credential_stored"] = bool(account_id and (_vault_root() / f"{account_id}.token").exists())
    if account.get("token_ref") and not redacted["credential_stored"]:
        redacted["status"] = "needs_reauth"
    return redacted


class ConnectorStore:
    def list_accounts(self, redact: bool = True) -> list[dict]:
        with _LOCK:
            accounts = _load_accounts()
        return [_redact_account(acc) if redact else dict(acc) for acc in accounts]

    def get_account(self, account_id: str) -> dict | None:
        with _LOCK:
            for acc in _load_accounts():
                if acc.get("account_id") == account_id:
                    return acc
        return None

    def save_account(self, account: ConnectedAccount, token: str | None = None) -> dict:
        with _LOCK:
            accounts = _load_accounts()
            record = account.to_dict(redact=False)
            key = _account_key(record)
            existing = next(
                (item for item in accounts
                 if item.get("account_id") == account.account_id or (
                     key[0] and key[1] and _account_key(item) == key
                 )),
                None,
            )
            if existing:
                # Reconnecting the same mailbox updates its durable record and
                # credential while preserving its stable account identifier.
                record["account_id"] = existing.get("account_id", account.account_id)
                record["created_at"] = existing.get("created_at") or record.get("created_at", "")
                if not token and existing.get("token_ref"):
                    record["token_ref"] = existing["token_ref"]

            final_id = record["account_id"]
            if token:
                record["token_ref"] = f"vault:{final_id}"
                self._store_token(final_id, token)
            accounts = [
                item for item in accounts
                if item.get("account_id") != final_id and not (
                    key[0] and key[1] and _account_key(item) == key
                )
            ]
            accounts.insert(0, record)
            _save_accounts(accounts)
        return _redact_account(record)

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
        _atomic_write_text(token_file, token)

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
