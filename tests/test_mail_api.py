"""Tests for mail API endpoints — no real network calls."""
import json
import pytest
from fastapi.testclient import TestClient
from src.warden.app import app


# ─── iCloud connect ──────────────────────────────────────────────────────────

def test_icloud_connect_stores_account(tmp_path, monkeypatch):
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/connectors/icloud/connect/app-password",
                       json={"email": "user@icloud.com", "app_password": "abcd-efgh-ijkl-mnop"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["provider"] == "icloud"
    assert data["display_email"] == "user@icloud.com"
    assert "account_id" in data

    # Vault has token file but it's not returned
    assert "abcd-efgh-ijkl-mnop" not in str(data)


def test_icloud_connect_rejects_no_password(tmp_path, monkeypatch):
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/connectors/icloud/connect/app-password",
                       json={"email": "user@icloud.com", "app_password": ""})
    assert resp.status_code == 400


def test_icloud_connect_rejects_invalid_email(tmp_path, monkeypatch):
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/connectors/icloud/connect/app-password",
                       json={"email": "not-an-email", "app_password": "abcd-efgh-ijkl-mnop"})
    assert resp.status_code == 400


def test_icloud_connect_never_returns_password(tmp_path, monkeypatch):
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    client = TestClient(app)
    resp = client.post("/api/mcharness/warden/connectors/icloud/connect/app-password",
                       json={"email": "user@icloud.com", "app_password": "super-secret-pass-xyz"})
    assert resp.status_code == 200
    assert "super-secret-pass-xyz" not in resp.text


# ─── Mail accounts ────────────────────────────────────────────────────────────

def test_mail_accounts_empty_initially():
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/mail/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["accounts"], list)


def test_mail_accounts_shows_connected(tmp_path, monkeypatch):
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    client = TestClient(app)
    # Connect iCloud account
    client.post("/api/mcharness/warden/connectors/icloud/connect/app-password",
                json={"email": "user@icloud.com", "app_password": "abcd-efgh-ijkl-mnop"})

    resp = client.get("/api/mcharness/warden/mail/accounts")
    assert resp.status_code == 200
    accounts = resp.json()["accounts"]
    assert any(a["provider"] == "icloud" for a in accounts)
    assert all("abcd-efgh-ijkl-mnop" not in str(a) for a in accounts)


# ─── Mail search ──────────────────────────────────────────────────────────────

def test_mail_search_unknown_account_404():
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/mail/search",
                      params={"account_id": "nonexistent-account-id", "q": "test"})
    assert resp.status_code == 404


def test_mail_search_icloud_mocked(tmp_path, monkeypatch):
    """iCloud search with mocked IMAP returns summaries."""
    import src.warden.connectors.store as store_mod
    import src.warden.mail.icloud as icloud_mod

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    client = TestClient(app)
    connect_resp = client.post(
        "/api/mcharness/warden/connectors/icloud/connect/app-password",
        json={"email": "user@icloud.com", "app_password": "test-pass-1234"})
    account_id = connect_resp.json()["account_id"]

    # Mock the ICloudMailProvider.search
    from src.warden.mail.models import MailMessageSummary
    mock_summaries = [MailMessageSummary(
        id="1", thread_id="t1", account_id=account_id, provider="icloud",
        from_addr="sender@example.com", to_addrs=["user@icloud.com"],
        subject="Test Subject", date="Mon, 1 Jan 2026 00:00:00 +0000",
        snippet="This is a test email snippet.",
    )]

    class MockProvider:
        def search(self, query, limit=10):
            return mock_summaries
        def read_message(self, mid):
            from src.warden.mail.models import MailMessage
            return MailMessage(summary=mock_summaries[0], body_text="Test body")
        def check_connection(self):
            return True

    import src.warden.mail.icloud as icloud_mod
    original = icloud_mod.build_icloud_provider
    monkeypatch.setattr(icloud_mod, "build_icloud_provider", lambda aid: MockProvider())

    resp = client.get("/api/mcharness/warden/mail/search",
                      params={"account_id": account_id, "q": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 1
    assert data["messages"][0]["subject"] == "Test Subject"
    assert "app_password" not in str(data)
    assert "test-pass-1234" not in str(data)


def test_mail_search_gmail_mocked(tmp_path, monkeypatch):
    """Gmail search with mocked provider returns summaries."""
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    # Manually insert a gmail account
    from src.warden.connectors.store import ConnectorStore
    from src.warden.connectors.models import ConnectedAccount
    acc = ConnectedAccount(
        account_id="gmail-test-01", user_id="local", provider="gmail",
        display_email="test@gmail.com", status="connected",
    )
    token_data = json.dumps({"access_token": "fake-at", "refresh_token": "fake-rt"})
    ConnectorStore().save_account(acc, token=token_data)

    from src.warden.mail.models import MailMessageSummary
    mock_summary = MailMessageSummary(
        id="msg-abc", thread_id="thr-abc", account_id="gmail-test-01",
        provider="gmail", from_addr="a@b.com", to_addrs=["test@gmail.com"],
        subject="Gmail Test", date="2026-01-01", snippet="Test Gmail snippet",
    )

    class MockGmailProvider:
        def search(self, query, limit=10): return [mock_summary]
        def read_message(self, mid):
            from src.warden.mail.models import MailMessage
            return MailMessage(summary=mock_summary, body_text="Gmail body")
        def check_connection(self): return True

    import src.warden.mail.gmail as gmail_mod
    monkeypatch.setattr(gmail_mod, "build_gmail_provider", lambda aid: MockGmailProvider())

    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/mail/search",
                      params={"account_id": "gmail-test-01", "q": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["messages"][0]["subject"] == "Gmail Test"
    assert "fake-at" not in str(data)
    assert "fake-rt" not in str(data)


# ─── Mail read_message ────────────────────────────────────────────────────────

def test_mail_read_message_icloud_mocked(tmp_path, monkeypatch):
    """Read message with mocked iCloud provider returns body_text, no HTML."""
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    client = TestClient(app)
    connect_resp = client.post(
        "/api/mcharness/warden/connectors/icloud/connect/app-password",
        json={"email": "user@icloud.com", "app_password": "test-pass-1234"})
    account_id = connect_resp.json()["account_id"]

    from src.warden.mail.models import MailMessage, MailMessageSummary
    summary = MailMessageSummary(
        id="42", thread_id="t42", account_id=account_id, provider="icloud",
        from_addr="a@b.com", to_addrs=["user@icloud.com"],
        subject="Read Test", date="2026-01-01", snippet="Body preview",
    )
    mock_msg = MailMessage(summary=summary, body_text="Full body text here",
                           body_html="<html>secret</html>")

    class MockProvider:
        def search(self, q, limit=10): return []
        def read_message(self, mid): return mock_msg
        def check_connection(self): return True

    import src.warden.mail.icloud as icloud_mod
    monkeypatch.setattr(icloud_mod, "build_icloud_provider", lambda aid: MockProvider())

    resp = client.get(f"/api/mcharness/warden/mail/messages/{account_id}/42")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["message"]["body_text"] == "Full body text here"
    assert "body_html" not in data["message"]
    assert "<html>secret</html>" not in str(data)


def test_mail_read_message_unknown_account_404():
    client = TestClient(app)
    resp = client.get("/api/mcharness/warden/mail/messages/nonexistent/msg-1")
    assert resp.status_code == 404


# ─── Redaction proof ──────────────────────────────────────────────────────────

def test_mail_api_never_returns_app_password(tmp_path, monkeypatch):
    import src.warden.connectors.store as store_mod
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(store_mod, "_vault_root", lambda: vault)

    client = TestClient(app)
    client.post("/api/mcharness/warden/connectors/icloud/connect/app-password",
                json={"email": "user@icloud.com", "app_password": "ultra-secret-xyz-987"})

    # Accounts endpoint
    accounts_resp = client.get("/api/mcharness/warden/mail/accounts")
    assert "ultra-secret-xyz-987" not in accounts_resp.text

    # Providers endpoint
    providers_resp = client.get("/api/mcharness/warden/connectors/providers")
    assert "ultra-secret-xyz-987" not in providers_resp.text


def test_mail_send_blocked_by_default():
    """mail.send is not exposed via API without explicit flag."""
    client = TestClient(app)
    # There is no POST /warden/mail/send — it doesn't exist in v0
    resp = client.post("/api/mcharness/warden/mail/send",
                       json={"account_id": "x", "to": "a@b.com", "subject": "test", "body": "hi"})
    assert resp.status_code == 404  # endpoint not registered
