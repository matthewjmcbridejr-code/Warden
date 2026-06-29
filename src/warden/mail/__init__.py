"""Warden Mail — normalized read-only mail access across iCloud, Gmail."""
from .models import MailMessage, MailMessageSummary, AttachmentMeta
from .base import MailProvider

__all__ = ["MailMessage", "MailMessageSummary", "AttachmentMeta", "MailProvider"]
