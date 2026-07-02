"""Email adapter tests: mock summary/draft/approval-gated send, capped counts."""
import pytest

from src.warden.resident.config import ResidentConfig
from src.warden.resident.email_adapter import DEFAULT_SUMMARY_CAP, EmailAdapter


def test_disabled_mode_returns_clear_response():
    cfg = ResidentConfig(email_mode="disabled")
    adapter = EmailAdapter(cfg)
    result = adapter.summarize()
    assert result["ok"] is False
    assert "disabled" in result["short_summary"].lower()


def test_mock_mode_summarize_returns_messages():
    cfg = ResidentConfig(email_mode="mock")
    adapter = EmailAdapter(cfg)
    result = adapter.summarize()
    assert result["ok"] is True
    assert result["key_fields"]["count"] >= 1


def test_mock_mode_summarize_incremental_no_duplicates():
    cfg = ResidentConfig(email_mode="mock")
    adapter = EmailAdapter(cfg)
    first = adapter.summarize()
    second = adapter.summarize()
    assert second["key_fields"]["count"] == 0  # nothing new since last_seen updated


def test_mock_mode_find_urgent():
    cfg = ResidentConfig(email_mode="mock")
    adapter = EmailAdapter(cfg)
    result = adapter.find_urgent()
    assert result["ok"] is True
    assert result["key_fields"]["count"] >= 1
    assert any("invoice" in m["subject"].lower() for m in result["raw"])


def test_mock_mode_search():
    cfg = ResidentConfig(email_mode="mock")
    adapter = EmailAdapter(cfg)
    result = adapter.search("weekly")
    assert result["ok"] is True
    assert result["key_fields"]["count"] == 1


def test_search_caps_at_default_limit():
    cfg = ResidentConfig(email_mode="mock")
    adapter = EmailAdapter(cfg)
    result = adapter.search("", limit=100)
    assert result["key_fields"]["count"] <= DEFAULT_SUMMARY_CAP


def test_draft_never_sends():
    cfg = ResidentConfig(email_mode="mock")
    adapter = EmailAdapter(cfg)
    draft = adapter.draft("bob@example.com", "Subject", "Body text")
    assert draft.ok is True
    assert draft.draft_id


def test_send_disabled_mode_blocked():
    cfg = ResidentConfig(email_mode="disabled")
    adapter = EmailAdapter(cfg)
    result = adapter.send("bob@example.com", "subj", "body", approved=True)
    assert result.ok is False
    assert "disabled" in result.reason.lower()


def test_send_without_approval_blocked():
    cfg = ResidentConfig(email_mode="mock", email_dry_run=False)
    adapter = EmailAdapter(cfg)
    result = adapter.send("bob@example.com", "subj", "body", approved=False)
    assert result.ok is False
    assert "approval" in result.reason.lower()


def test_send_dry_run_blocked_even_when_approved():
    cfg = ResidentConfig(email_mode="mock", email_dry_run=True)
    adapter = EmailAdapter(cfg)
    result = adapter.send("bob@example.com", "subj", "body", approved=True)
    assert result.ok is False
    assert "dry-run" in result.reason.lower()


def test_send_approved_non_dry_run_still_not_implemented():
    cfg = ResidentConfig(email_mode="mock", email_dry_run=False)
    adapter = EmailAdapter(cfg)
    result = adapter.send("bob@example.com", "subj", "body", approved=True)
    assert result.ok is False
    assert "not implemented" in result.reason.lower()
