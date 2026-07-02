"""Telegram-safe compact formatting.

Keeps replies short by default (3-8 bullets or a short paragraph), truncates
overly long content and points at an artifact/report path instead, and
supports a "reply MORE" expansion pattern by caching the full text keyed by
chat id.
"""
from __future__ import annotations

from typing import Any

_MORE_CACHE: dict[Any, str] = {}

DEFAULT_MAX_CHARS = 900
MORE_HINT = "\n\n(truncated — reply \"more\" for the full output)"


def format_bullets(items: list[str], max_items: int = 8) -> str:
    """Render a bounded bullet list."""
    trimmed = items[:max_items]
    lines = [f"- {i}" for i in trimmed]
    if len(items) > max_items:
        lines.append(f"...and {len(items) - max_items} more")
    return "\n".join(lines)


def truncate_for_chat(text: str, max_chars: int = DEFAULT_MAX_CHARS, *, chat_id: Any = None) -> tuple[str, bool]:
    """Truncate text to a Telegram-friendly length. Returns (text, truncated).

    If truncated and chat_id is given, the full text is cached so a
    subsequent "more" reply can retrieve it via get_more().
    """
    if len(text) <= max_chars:
        return text, False
    if chat_id is not None:
        _MORE_CACHE[chat_id] = text
    cut = text[: max_chars - len(MORE_HINT)].rstrip()
    return cut + MORE_HINT, True


def get_more(chat_id: Any, max_chars: int = 3500) -> str | None:
    """Return the cached full text for a chat (possibly still truncated to a
    hard ceiling to avoid enormous Telegram messages), or None if nothing cached."""
    full = _MORE_CACHE.get(chat_id)
    if full is None:
        return None
    if len(full) > max_chars:
        return full[:max_chars].rstrip() + "\n\n(still truncated — see artifact for full output)"
    return full


def is_more_request(text: str) -> bool:
    return text.strip().lower() in ("more", "/more", "reply more", "show more")


def artifact_reference(path: str) -> str:
    return f"Full output written to: {path}"
