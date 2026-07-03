"""Abstract base for mail providers — all providers implement this interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from .models import MailMessage, MailMessageSummary


class MailProvider(ABC):
    """Interface for all mail providers (iCloud IMAP, Gmail API, Outlook Graph)."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[MailMessageSummary]:
        """Search mail. Returns summaries (no body)."""

    @abstractmethod
    def read_message(self, message_id: str) -> MailMessage:
        """Read a single message by ID. Returns full message with body_text."""

    @abstractmethod
    def check_connection(self) -> bool:
        """Quick connectivity check. Returns True if provider is reachable."""
