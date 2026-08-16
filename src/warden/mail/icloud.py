"""iCloud Mail provider — IMAP with app-specific password."""
from __future__ import annotations
import email as _email_module
import email.header
import imaplib
import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from .base import MailProvider
from .models import AttachmentMeta, MailMessage, MailMessageSummary

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.mail.me.com"
IMAP_PORT = 993


def _imap_timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("WARDEN_MAIL_CONNECT_TIMEOUT_SECONDS", "6")))
    except ValueError:
        return 6.0

# Injected in tests to skip real IMAP connections
_imap_factory = None  # callable(host, port) -> IMAP4_SSL-like object


def set_imap_factory(fn) -> None:
    """Override IMAP connection factory (for testing)."""
    global _imap_factory
    _imap_factory = fn


def _make_imap(host: str, port: int):
    if _imap_factory is not None:
        return _imap_factory(host, port)
    return imaplib.IMAP4_SSL(host, port, timeout=_imap_timeout_seconds())


def _decode_header(raw: str) -> str:
    """Decode RFC2047 encoded mail header."""
    if not raw:
        return ""
    try:
        parts = email.header.decode_header(raw)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(str(part))
        return " ".join(decoded)
    except Exception:
        return str(raw)


def _sanitize_text(text: str, max_len: int = 8000) -> str:
    """Strip control chars and truncate."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    return text[:max_len]


def _snippet(text: str, max_len: int = 200) -> str:
    return _sanitize_text(text.replace("\n", " ").replace("\r", "").strip(), max_len)


def _parse_message(raw_bytes: bytes, message_id: str, account_id: str) -> MailMessage:
    """Parse raw RFC822 bytes into MailMessage."""
    msg = _email_module.message_from_bytes(raw_bytes)
    subject = _decode_header(msg.get("Subject", ""))
    from_addr = _decode_header(msg.get("From", ""))
    to_raw = msg.get("To", "")
    to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()] if to_raw else []
    date_str = msg.get("Date", "")
    thread_id = msg.get("Message-ID", message_id).strip("<>")

    body_text = ""
    body_html = ""
    attachments: list[AttachmentMeta] = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                fn = part.get_filename() or "attachment"
                attachments.append(AttachmentMeta(
                    filename=_decode_header(fn),
                    mime_type=ct,
                    size_bytes=len(part.get_payload(decode=True) or b""),
                ))
            elif ct == "text/plain" and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            elif ct == "text/html" and not body_html:
                payload = part.get_payload(decode=True)
                if payload:
                    body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body_text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

    body_text = _sanitize_text(body_text)
    summary = MailMessageSummary(
        id=message_id,
        thread_id=thread_id,
        account_id=account_id,
        provider="icloud",
        from_addr=from_addr,
        to_addrs=to_addrs,
        subject=subject,
        date=date_str,
        snippet=_snippet(body_text or body_html),
        has_attachments=bool(attachments),
    )
    return MailMessage(summary=summary, body_text=body_text, body_html="", attachments=attachments)


class ICloudMailProvider(MailProvider):
    """iCloud Mail via IMAP4_SSL using app-specific password."""

    def __init__(self, email_addr: str, app_password: str, account_id: str):
        self._email = email_addr
        self._password = app_password
        self._account_id = account_id

    def _connect(self):
        imap = _make_imap(IMAP_HOST, IMAP_PORT)
        imap.login(self._email, self._password)
        return imap

    def check_connection(self) -> bool:
        try:
            imap = self._connect()
            imap.logout()
            return True
        except Exception as e:
            logger.warning("iCloud connection check failed: %s", e)
            return False

    def search(self, query: str, limit: int = 10) -> list[MailMessageSummary]:
        imap = self._connect()
        try:
            imap.select("INBOX", readonly=True)
            # Build simple IMAP search criteria
            imap_query = _build_imap_query(query)
            status, data = imap.search(None, imap_query)
            if status != "OK":
                return []
            # iCloud can return [None] for a successful search with no matches.
            raw_ids = data[0] if data and data[0] else b""
            msg_ids = raw_ids.split()
            msg_ids = msg_ids[-limit:]  # most recent
            summaries = []
            for mid in reversed(msg_ids):
                try:
                    status2, msg_data = imap.fetch(mid, "(RFC822.HEADER)")
                    if status2 != "OK" or not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                    msg = _email_module.message_from_bytes(raw)
                    subject = _decode_header(msg.get("Subject", ""))
                    from_addr = _decode_header(msg.get("From", ""))
                    to_raw = msg.get("To", "")
                    to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()]
                    date_str = msg.get("Date", "")
                    summaries.append(MailMessageSummary(
                        id=mid.decode() if isinstance(mid, bytes) else str(mid),
                        thread_id=msg.get("Message-ID", "").strip("<>"),
                        account_id=self._account_id,
                        provider="icloud",
                        from_addr=from_addr,
                        to_addrs=to_addrs,
                        subject=subject,
                        date=date_str,
                        snippet="",
                    ))
                except Exception as e:
                    logger.warning("Error fetching message %s: %s", mid, e)
            return summaries
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def read_message(self, message_id: str) -> MailMessage:
        imap = self._connect()
        try:
            imap.select("INBOX", readonly=True)
            status, msg_data = imap.fetch(message_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                raise ValueError(f"Message {message_id} not found")
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
            return _parse_message(raw, message_id, self._account_id)
        finally:
            try:
                imap.logout()
            except Exception:
                pass


def _build_imap_query(query: str) -> str:
    """Convert a simple text query to IMAP search criteria."""
    q = query.strip()
    if not q:
        return "ALL"
    # Simple: search SUBJECT and FROM and TEXT with first 2 terms
    terms = q.split()[:2]
    if len(terms) == 1:
        return f'TEXT "{terms[0]}"'
    return f'OR TEXT "{terms[0]}" TEXT "{terms[1]}"'


def build_icloud_provider(account_id: str) -> "ICloudMailProvider | None":
    """Build provider from stored vault token. Returns None if account not found."""
    from ..connectors.store import ConnectorStore
    store = ConnectorStore()
    acc = store.get_account(account_id)
    if not acc or acc.get("provider") != "icloud":
        return None
    token_str = store._get_token(account_id)
    if not token_str:
        return None
    try:
        creds = json.loads(token_str)
        return ICloudMailProvider(
            email_addr=creds["email"],
            app_password=creds["app_password"],
            account_id=account_id,
        )
    except Exception:
        return None
