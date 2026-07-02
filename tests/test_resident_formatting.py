"""Telegram-safe formatting/truncation tests."""
from src.warden.resident.formatting import (
    MORE_HINT,
    format_bullets,
    get_more,
    is_more_request,
    truncate_for_chat,
)


def test_format_bullets_caps_items():
    items = [f"item {i}" for i in range(20)]
    out = format_bullets(items, max_items=5)
    lines = out.splitlines()
    assert len(lines) == 6  # 5 bullets + "...and N more"
    assert "and 15 more" in lines[-1]


def test_format_bullets_no_overflow_line_when_within_limit():
    out = format_bullets(["a", "b"], max_items=8)
    assert "more" not in out


def test_truncate_short_text_unchanged():
    text = "short text"
    out, truncated = truncate_for_chat(text, max_chars=900)
    assert out == text
    assert truncated is False


def test_truncate_long_text_gets_hint_and_flag():
    text = "x" * 2000
    out, truncated = truncate_for_chat(text, max_chars=100, chat_id=42)
    assert truncated is True
    assert MORE_HINT in out
    assert len(out) <= 100 + len(MORE_HINT)


def test_get_more_returns_cached_full_text():
    text = "y" * 2000
    truncate_for_chat(text, max_chars=100, chat_id=99)
    full = get_more(99)
    assert full is not None
    assert len(full) <= 3500


def test_get_more_returns_none_when_nothing_cached():
    assert get_more("no-such-chat-id-ever") is None


def test_is_more_request_variants():
    assert is_more_request("more")
    assert is_more_request("MORE")
    assert is_more_request(" more ")
    assert is_more_request("/more")
    assert not is_more_request("more context please explain")
