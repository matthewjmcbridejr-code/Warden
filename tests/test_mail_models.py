"""Tests for mail data models."""
import pytest
from src.warden.mail.models import MailMessage, MailMessageSummary, AttachmentMeta


def _make_summary(**kwargs):
    defaults = dict(
        id="msg-1", thread_id="thread-1", account_id="acc-1",
        provider="icloud", from_addr="a@b.com", to_addrs=["c@d.com"],
        subject="Test", date="2026-01-01T00:00:00Z", snippet="Hello"
    )
    defaults.update(kwargs)
    return MailMessageSummary(**defaults)


def test_summary_to_dict():
    s = _make_summary()
    d = s.to_dict()
    assert d["id"] == "msg-1"
    assert d["provider"] == "icloud"
    assert "snippet" in d
    assert "body_text" not in d  # summary has no body


def test_message_to_dict_no_html():
    s = _make_summary()
    msg = MailMessage(summary=s, body_text="Hello world", body_html="<p>secret</p>")
    d = msg.to_dict(include_html=False)
    assert d["body_text"] == "Hello world"
    assert "body_html" not in d
    assert "<p>secret</p>" not in str(d)


def test_message_to_dict_with_html_explicit():
    s = _make_summary()
    msg = MailMessage(summary=s, body_text="Hello", body_html="<p>Hi</p>")
    d = msg.to_dict(include_html=True)
    assert "body_html" in d


def test_attachment_meta():
    att = AttachmentMeta(filename="resume.pdf", mime_type="application/pdf", size_bytes=12345)
    d = att.to_dict()
    assert d["filename"] == "resume.pdf"
    assert d["size_bytes"] == 12345


def test_summary_has_no_token_fields():
    s = _make_summary()
    d = s.to_dict()
    for key in d:
        assert "token" not in key.lower()
        assert "password" not in key.lower()
        assert "secret" not in key.lower()
