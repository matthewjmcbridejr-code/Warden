"""Inbound/outbound message dataclasses for the resident agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class InboundMessage:
    """A message received from a transport (Telegram, etc.)."""
    text: str
    user_id: int | None = None
    chat_id: int | None = None
    transport: str = "telegram"
    update_id: int | None = None
    received_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """A reply to send back to the user via a transport."""
    text: str
    chat_id: int | None = None
    parse_mode: str | None = None
    artifact_path: str | None = None
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "chat_id": self.chat_id,
            "parse_mode": self.parse_mode,
            "artifact_path": self.artifact_path,
            "truncated": self.truncated,
        }
