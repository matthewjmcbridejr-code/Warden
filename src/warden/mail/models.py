"""Normalized mail data models shared across all providers."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class MailMessageSummary:
    """Lightweight summary — safe to return to agents."""
    id: str
    thread_id: str
    account_id: str
    provider: str
    from_addr: str
    to_addrs: list[str]
    subject: str
    date: str  # ISO8601
    snippet: str  # first ~200 chars, sanitized
    labels: list[str] = field(default_factory=list)
    has_attachments: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "account_id": self.account_id,
            "provider": self.provider,
            "from_addr": self.from_addr,
            "to_addrs": self.to_addrs,
            "subject": self.subject,
            "date": self.date,
            "snippet": self.snippet,
            "labels": self.labels,
            "has_attachments": self.has_attachments,
        }


@dataclass
class AttachmentMeta:
    filename: str
    mime_type: str
    size_bytes: int = 0

    def to_dict(self) -> dict:
        return {"filename": self.filename, "mime_type": self.mime_type,
                "size_bytes": self.size_bytes}


@dataclass
class MailMessage:
    """Full message — body_html not returned by default."""
    summary: MailMessageSummary
    body_text: str = ""  # plain text body, sanitized
    body_html: str = ""  # HTML body — never exposed via API by default
    attachments: list[AttachmentMeta] = field(default_factory=list)

    def to_dict(self, include_html: bool = False) -> dict:
        d = {
            **self.summary.to_dict(),
            "body_text": self.body_text,
            "attachments": [a.to_dict() for a in self.attachments],
        }
        if include_html:
            d["body_html"] = self.body_html
        return d
