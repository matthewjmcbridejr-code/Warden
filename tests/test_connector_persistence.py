"""Connector vault persistence and multi-account behavior."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from src.warden.connectors.models import ConnectedAccount
from src.warden.connectors.oauth import _extract_email_from_token
from src.warden.connectors.store import ConnectorStore
import src.warden.connectors.store as store_mod


def _account(account_id: str, provider: str, email: str) -> ConnectedAccount:
    return ConnectedAccount(
        account_id=account_id,
        user_id="local",
        provider=provider,
        display_email=email,
        status="connected",
        capabilities=["mail.read", "mail.search"],
        created_at="2026-07-16T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
    )


def test_reconnect_same_email_updates_stable_record(tmp_path, monkeypatch):
    vault = tmp_path / "connectors"
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)
    store = ConnectorStore()

    first = store.save_account(
        _account("gmail-first", "gmail", "person@example.com"),
        token="first-credential",
    )
    second = store.save_account(
        _account("gmail-reconnect", "gmail", "PERSON@example.com"),
        token="replacement-credential",
    )

    accounts = store.list_accounts(redact=True)
    assert len(accounts) == 1
    assert first["account_id"] == second["account_id"] == "gmail-first"
    assert accounts[0]["credential_stored"] is True
    assert store._get_token("gmail-first") == "replacement-credential"
    assert not (vault / "gmail-reconnect.token").exists()


def test_corrupt_manifest_falls_back_to_last_valid_backup(tmp_path, monkeypatch):
    vault = tmp_path / "connectors"
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)
    store = ConnectorStore()

    store.save_account(_account("gmail-one", "gmail", "one@gmail.com"), token="one")
    store.save_account(_account("icloud-two", "icloud", "two@icloud.com"), token="two")
    (vault / "accounts.json").write_text("not valid json")

    recovered = store.list_accounts(redact=True)
    assert [item["account_id"] for item in recovered] == ["gmail-one"]


def test_vault_files_are_private_and_atomic_temps_are_cleaned(tmp_path, monkeypatch):
    vault = tmp_path / "connectors"
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)
    ConnectorStore().save_account(
        _account("outlook-one", "outlook", "one@outlook.com"),
        token="oauth-token",
    )

    assert (vault.stat().st_mode & 0o777) == 0o700
    assert ((vault / "accounts.json").stat().st_mode & 0o777) == 0o600
    assert ((vault / "outlook-one.token").stat().st_mode & 0o777) == 0o600
    assert not list(vault.glob(".*.tmp"))


def test_microsoft_preferred_username_is_used_as_mailbox_address():
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({
        "preferred_username": "mattmcbride1@hotmail.com"
    }).encode()).rstrip(b"=").decode()
    token = {"id_token": f"{header}.{payload}.signature"}

    assert _extract_email_from_token(token, "outlook") == "mattmcbride1@hotmail.com"


def test_mail_ui_keeps_multi_account_controls_visible():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "web" / "warden" / "app.js").read_text()
    app_html = (root / "web" / "warden" / "app.html").read_text()

    assert 'if (p.provider_id === "gmail")' in app_js
    assert 'p.provider_id === "gmail" && !isConnected' not in app_js
    assert "Add another Google mailbox" in app_js
    assert "Add another Microsoft account" in app_js
    assert "Add another iCloud mailbox" in app_js
    assert 'data-scroll-target="mail-accounts-panel"' in app_html
