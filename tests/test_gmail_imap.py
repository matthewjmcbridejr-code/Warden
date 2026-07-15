"""Tests for Gmail IMAP app-password connector — no real IMAP connections."""
import email as _email
import imaplib
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from src.warden.app import app
import src.warden.connectors.store as store_mod
import src.warden.mail.gmail_imap as gmail_imap_mod


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_imap_factory():
    """Reset injected IMAP factory after each test."""
    gmail_imap_mod.set_imap_factory(None)
    yield
    gmail_imap_mod.set_imap_factory(None)


def _make_fake_imap(search_ids: list[bytes] | None = None, message_raw: bytes | None = None):
    """Build a fake IMAP4_SSL-like object."""
    imap = MagicMock()
    imap.login = MagicMock(return_value=("OK", [b"Logged in"]))
    imap.logout = MagicMock(return_value=("BYE", []))
    ids = search_ids if search_ids is not None else [b"1", b"2"]
    imap.search = MagicMock(return_value=("OK", [b" ".join(ids)]))
    imap.select = MagicMock(return_value=("OK", [b"2"]))

    # Build a minimal RFC822 header for fetch
    if message_raw is None:
        raw_header = (
            b"From: sender@example.com\r\n"
            b"To: me@gmail.com\r\n"
            b"Subject: Test Subject\r\n"
            b"Date: Tue, 10 Jun 2025 10:00:00 +0000\r\n"
            b"Message-ID: <abc123@example.com>\r\n"
            b"\r\n"
            b"Hello from test."
        )
    else:
        raw_header = message_raw

    imap.fetch = MagicMock(return_value=("OK", [(b"1 (RFC822.HEADER {100})", raw_header)]))
    return imap


def _make_client(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)
    return TestClient(app)


# ─── API: Gmail IMAP connect endpoint ─────────────────────────────────────────

def test_gmail_imap_connect_stores_account(tmp_path, monkeypatch):
    fake = _make_fake_imap()
    gmail_imap_mod.set_imap_factory(lambda h, p: fake)
    client = _make_client(tmp_path, monkeypatch)
    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/app-password",
                       json={"email": "user@gmail.com", "app_password": "abcdefghijklmnop"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["provider"] == "gmail"
    assert data["auth_type"] == "imap_app_password"
    assert data["display_email"] == "user@gmail.com"
    assert "account_id" in data


def test_gmail_imap_connect_password_not_in_response(tmp_path, monkeypatch):
    fake = _make_fake_imap()
    gmail_imap_mod.set_imap_factory(lambda h, p: fake)
    client = _make_client(tmp_path, monkeypatch)
    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/app-password",
                       json={"email": "user@gmail.com", "app_password": "SECRET-APP-PASS-1234"})
    assert "SECRET-APP-PASS-1234" not in resp.text
    # auth_type field may contain "app_password" as a label — but the value must not
    assert resp.json().get("app_password") is None


def test_gmail_imap_connect_rejects_no_password(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/app-password",
                       json={"email": "user@gmail.com", "app_password": ""})
    assert resp.status_code == 400


def test_gmail_imap_connect_rejects_invalid_email(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/app-password",
                       json={"email": "not-an-email", "app_password": "abcdefghijklmnop"})
    assert resp.status_code == 400


def test_gmail_imap_connect_bad_password_friendly_error(tmp_path, monkeypatch):
    """Bad app password returns friendly message, not raw IMAP error."""
    def bad_login(h, p):
        imap = MagicMock()
        imap.login = MagicMock(side_effect=imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials (Failure)"))
        return imap
    gmail_imap_mod.set_imap_factory(bad_login)
    client = _make_client(tmp_path, monkeypatch)
    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/app-password",
                       json={"email": "user@gmail.com", "app_password": "wrongpassword12"})
    assert resp.status_code == 422
    assert "app password" in resp.json()["detail"].lower() or "gmail" in resp.json()["detail"].lower()
    assert "[AUTHENTICATIONFAILED]" not in resp.json()["detail"]


# ─── Gmail IMAP Provider unit tests ───────────────────────────────────────────

def test_gmail_imap_provider_search(tmp_path):
    fake = _make_fake_imap(search_ids=[b"5", b"6"])
    gmail_imap_mod.set_imap_factory(lambda h, p: fake)
    provider = gmail_imap_mod.GmailImapProvider("user@gmail.com", "apppass", "acct-1")
    results = provider.search("test query", limit=5)
    assert isinstance(results, list)
    assert all(hasattr(r, "subject") for r in results)


def test_gmail_imap_provider_search_returns_no_raw_imap_tuples(tmp_path):
    fake = _make_fake_imap()
    gmail_imap_mod.set_imap_factory(lambda h, p: fake)
    provider = gmail_imap_mod.GmailImapProvider("user@gmail.com", "apppass", "acct-1")
    results = provider.search("hello", limit=3)
    for r in results:
        r_str = str(r)
        assert "FLAGS" not in r_str
        assert "BODYSTRUCTURE" not in r_str
        assert "RFC822" not in r_str
        assert "211 ()" not in r_str


def test_gmail_imap_provider_read_message():
    raw_msg = (
        b"From: sender@example.com\r\n"
        b"To: me@gmail.com\r\n"
        b"Subject: Hello World\r\n"
        b"Date: Mon, 9 Jun 2025 09:00:00 +0000\r\n"
        b"Message-ID: <hello@example.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"This is the email body."
    )
    fake = _make_fake_imap(message_raw=raw_msg)
    fake.fetch = MagicMock(return_value=("OK", [(b"1 (RFC822 {100})", raw_msg)]))
    gmail_imap_mod.set_imap_factory(lambda h, p: fake)
    provider = gmail_imap_mod.GmailImapProvider("user@gmail.com", "apppass", "acct-1")
    msg = provider.read_message("1")
    assert msg.summary.subject == "Hello World"
    assert msg.summary.from_addr == "sender@example.com"
    assert "This is the email body" in msg.body_text


def test_gmail_imap_provider_read_no_body_html():
    """body_html must never be returned (only body_text)."""
    raw_msg = (
        b"From: sender@example.com\r\n"
        b"To: me@gmail.com\r\n"
        b"Subject: HTML Test\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><p>Hello <b>world</b></p></body></html>"
    )
    fake = _make_fake_imap(message_raw=raw_msg)
    fake.fetch = MagicMock(return_value=("OK", [(b"1 (RFC822 {100})", raw_msg)]))
    gmail_imap_mod.set_imap_factory(lambda h, p: fake)
    provider = gmail_imap_mod.GmailImapProvider("user@gmail.com", "apppass", "acct-1")
    msg = provider.read_message("1")
    # body_html stripped to empty, HTML tags stripped from body_text
    assert msg.body_html == ""
    assert "<html>" not in msg.body_text
    assert "Hello" in msg.body_text  # text extracted from HTML


def test_gmail_imap_provider_read_no_secrets_in_dict():
    raw_msg = (
        b"From: sender@example.com\r\n"
        b"Subject: Test\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"Normal email content."
    )
    fake = _make_fake_imap(message_raw=raw_msg)
    fake.fetch = MagicMock(return_value=("OK", [(b"1 (RFC822 {100})", raw_msg)]))
    gmail_imap_mod.set_imap_factory(lambda h, p: fake)
    provider = gmail_imap_mod.GmailImapProvider("user@gmail.com", "apppass", "acct-1")
    msg = provider.read_message("1")
    d = msg.to_dict(include_html=False)
    text = str(d)
    assert "access_token" not in text
    assert "app_password" not in text
    assert "refresh_token" not in text


# ─── build_gmail_imap_provider ───────────────────────────────────────────────

def test_build_gmail_imap_provider_returns_none_for_missing_account(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)
    result = gmail_imap_mod.build_gmail_imap_provider("nonexistent-account")
    assert result is None


def test_build_gmail_imap_provider_returns_none_for_oauth_account(tmp_path, monkeypatch):
    """OAuth tokens don't have app_password — builder returns None."""
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)
    from src.warden.connectors.store import ConnectorStore
    from src.warden.connectors.models import ConnectedAccount
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    store = ConnectorStore()
    acc = ConnectedAccount(
        account_id="gmail-oauth-test",
        user_id="local",
        provider="gmail",
        display_email="user@gmail.com",
        status="connected",
        scopes=[],
        capabilities=["mail.read"],
        created_at=now,
        updated_at=now,
    )
    # OAuth token has no app_password
    store.save_account(acc, token=json.dumps({"access_token": "ya29.xxx", "refresh_token": "yyy"}))
    result = gmail_imap_mod.build_gmail_imap_provider("gmail-oauth-test")
    assert result is None  # correctly falls through to OAuth provider path


# ─── API: mail search routes through IMAP ────────────────────────────────────

def test_mail_search_uses_gmail_imap(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)
    fake = _make_fake_imap()
    gmail_imap_mod.set_imap_factory(lambda h, p: fake)
    client = TestClient(app)

    # First connect
    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/app-password",
                       json={"email": "user@gmail.com", "app_password": "abcdefghijklmnop"})
    assert resp.status_code == 200
    account_id = resp.json()["account_id"]

    # Then search
    resp2 = client.get(f"/api/mcharness/warden/mail/search?account_id={account_id}&q=hello")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["ok"] is True
    assert "messages" in data
    # No raw IMAP junk in snippets
    for m in data["messages"]:
        snippet = str(m)
        assert "FLAGS" not in snippet
        assert "BODYSTRUCTURE" not in snippet


def test_mail_search_no_token_in_response(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)
    fake = _make_fake_imap()
    gmail_imap_mod.set_imap_factory(lambda h, p: fake)
    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/connectors/gmail/connect/app-password",
                       json={"email": "user@gmail.com", "app_password": "mysecretpass1234"})  # gitleaks:allow
    account_id = resp.json()["account_id"]
    resp2 = client.get(f"/api/mcharness/warden/mail/search?account_id={account_id}&q=test")
    assert "mysecretpass1234" not in resp2.text
    assert "app_password" not in resp2.text
    assert "access_token" not in resp2.text
