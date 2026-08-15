"""Gmail OAuth durability tests — no real Google requests."""
from __future__ import annotations

import json
import urllib.parse

from src.warden.connectors import oauth as oauth_mod
from src.warden.connectors.store import ConnectorStore
from src.warden.mail import gmail as gmail_mod


def test_oauth_state_records_the_scopes_granted_to_the_mailbox(monkeypatch):
    monkeypatch.setenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("WARDEN_GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    oauth_mod._STATES.clear()

    result = oauth_mod.start_oauth_flow("gmail", "http://127.0.0.1:6969")
    state = oauth_mod.validate_callback_state(result["state"])

    assert result["provider"] == "gmail"
    assert state is not None
    assert state["scopes"] == oauth_mod.GMAIL_SCOPES


def test_expired_access_token_refreshes_from_vault_config_and_persists(tmp_path, monkeypatch):
    connector_vault = tmp_path / "connectors"
    connector_vault.mkdir()

    import src.warden.connectors.store as store_mod
    monkeypatch.setattr(store_mod, "_vault_root", lambda: connector_vault)
    monkeypatch.setattr(
        oauth_mod,
        "get_provider_credentials",
        lambda provider: ("vault-client-id", "vault-client-secret"),
    )

    store = ConnectorStore()
    store._store_token("gmail-oauth", json.dumps({
        "access_token": "expired-access",
        "refresh_token": "durable-refresh",
        "token_type": "Bearer",
    }))

    calls = []

    def fake_http(method, url, headers, body):
        calls.append((method, url, body))
        if method == "GET" and len([c for c in calls if c[0] == "GET"]) == 1:
            raise gmail_mod.TokenExpiredError("expired")
        if method == "POST":
            form = urllib.parse.parse_qs(body.decode())
            assert form["client_id"] == ["vault-client-id"]
            assert form["client_secret"] == ["vault-client-secret"]
            assert form["refresh_token"] == ["durable-refresh"]
            return {"access_token": "fresh-access", "expires_in": 3600, "token_type": "Bearer"}
        return {"emailAddress": "person@example.com"}

    gmail_mod.set_http_client(fake_http)
    try:
        provider = gmail_mod.GmailProvider(
            account_id="gmail-oauth",
            access_token="expired-access",
            refresh_token="durable-refresh",
        )
        assert provider.check_connection() is True
    finally:
        gmail_mod.set_http_client(None)

    persisted = json.loads(store._get_token("gmail-oauth"))
    assert persisted["access_token"] == "fresh-access"
    assert persisted["refresh_token"] == "durable-refresh"
    assert persisted["expires_in"] == 3600
    assert persisted["refreshed_at"]

