"""Gmail Mail provider — IMAP with Google App Password.

No OAuth required. User must have 2-Step Verification enabled and create
a Google App Password in Google Account → Security → App passwords.
Do not use the normal Google account password.

Gmail IMAP settings:
  host: imap.gmail.com, port: 993, SSL/TLS
  username: full Gmail address
  password: Google App Password (16-char, no spaces)
"""
from __future__ import annotations
import email as _email_module
import email.header
import imaplib
import json
import logging
import re
from typing import Any

from .base import MailProvider
from .models import AttachmentMeta, MailMessage, MailMessageSummary

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

_imap_factory = None  # test injection: callable(host, port) -> IMAP4_SSL-like


def set_imap_factory(fn) -> None:
    global _imap_factory
    _imap_factory = fn


def _make_imap(host: str, port: int):
    if _imap_factory is not None:
        return _imap_factory(host, port)
    return imaplib.IMAP4_SSL(host, port)


def _decode_header(raw: str) -> str:
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
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    return text[:max_len]


def _snippet(text: str, max_len: int = 200) -> str:
    return _sanitize_text(text.replace("\n", " ").replace("\r", "").strip(), max_len)


def _parse_message(raw_bytes: bytes, message_id: str, account_id: str) -> MailMessage:
    msg = _email_module.message_from_bytes(raw_bytes)
    subject = _decode_header(msg.get("Subject", ""))
    from_addr = _decode_header(msg.get("From", ""))
    to_raw = msg.get("To", "")
    to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()] if to_raw else []
    date_str = msg.get("Date", "")
    thread_id = msg.get("Message-ID", message_id).strip("<>")

    body_text = ""
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
            elif ct == "text/html" and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    raw_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    # Strip HTML tags for text fallback
                    body_text = re.sub(r"<[^>]+>", " ", raw_html)
                    body_text = re.sub(r"\s+", " ", body_text).strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            raw = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                raw = re.sub(r"<[^>]+>", " ", raw)
                raw = re.sub(r"\s+", " ", raw).strip()
            body_text = raw

    body_text = _sanitize_text(body_text)
    summary = MailMessageSummary(
        id=message_id,
        thread_id=thread_id,
        account_id=account_id,
        provider="gmail",
        from_addr=from_addr,
        to_addrs=to_addrs,
        subject=subject,
        date=date_str,
        snippet=_snippet(body_text),
        has_attachments=bool(attachments),
    )
    return MailMessage(summary=summary, body_text=body_text, body_html="", attachments=attachments)


def _build_imap_query(query: str) -> str:
    q = query.strip()
    if not q or q == "ALL":
        return "ALL"
    terms = q.split()[:2]
    if len(terms) == 1:
        return f'TEXT "{terms[0]}"'
    return f'OR TEXT "{terms[0]}" TEXT "{terms[1]}"'


class GmailImapProvider(MailProvider):
    """Gmail IMAP using Google App Password. No OAuth required."""

    def __init__(self, email_addr: str, app_password: str, account_id: str):
        self._email = email_addr
        self._password = app_password
        self._account_id = account_id

    def _connect(self):
        imap = _make_imap(IMAP_HOST, IMAP_PORT)
        try:
            imap.login(self._email, self._password)
        except imaplib.IMAP4.error as exc:
            msg = str(exc)
            if "AUTHENTICATE" in msg or "Invalid credentials" in msg or "Application-specific" in msg:
                raise ValueError(
                    "Gmail rejected the app password. Confirm IMAP is enabled in Gmail settings "
                    "and that this is a Google App Password (not your normal password)."
                ) from exc
            raise
        return imap

    def check_connection(self) -> bool:
        try:
            imap = self._connect()
            imap.logout()
            return True
        except ValueError:
            raise  # propagate auth errors — caller decides how to handle
        except Exception as e:
            logger.warning("Gmail IMAP connection check failed: %s", e)
            return False

    def search(self, query: str, limit: int = 10) -> list[MailMessageSummary]:
        imap = self._connect()
        try:
            imap.select("[Gmail]/All Mail", readonly=True)
            imap_query = _build_imap_query(query)
            status, data = imap.search(None, imap_query)
            if status != "OK":
                return []
            msg_ids = data[0].split()
            msg_ids = msg_ids[-limit:]
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
                        provider="gmail",
                        from_addr=from_addr,
                        to_addrs=to_addrs,
                        subject=subject,
                        date=date_str,
                        snippet="",
                    ))
                except Exception as e:
                    logger.warning("Error fetching Gmail message %s: %s", mid, e)
            return summaries
        except imaplib.IMAP4.error:
            # [Gmail]/All Mail may not exist on all accounts; fall back to INBOX
            try:
                imap.select("INBOX", readonly=True)
                imap_query = _build_imap_query(query)
                status, data = imap.search(None, imap_query)
                if status != "OK":
                    return []
                msg_ids = data[0].split()[-limit:]
                summaries = []
                for mid in reversed(msg_ids):
                    try:
                        status2, msg_data = imap.fetch(mid, "(RFC822.HEADER)")
                        if status2 != "OK" or not msg_data or not msg_data[0]:
                            continue
                        raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                        msg = _email_module.message_from_bytes(raw)
                        summaries.append(MailMessageSummary(
                            id=mid.decode() if isinstance(mid, bytes) else str(mid),
                            thread_id=msg.get("Message-ID", "").strip("<>"),
                            account_id=self._account_id,
                            provider="gmail",
                            from_addr=_decode_header(msg.get("From", "")),
                            to_addrs=[],
                            subject=_decode_header(msg.get("Subject", "")),
                            date=msg.get("Date", ""),
                            snippet="",
                        ))
                    except Exception:
                        pass
                return summaries
            except Exception:
                return []
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def read_message(self, message_id: str) -> MailMessage:
        imap = self._connect()
        try:
            # Try All Mail first, fall back to INBOX
            for mailbox in ["[Gmail]/All Mail", "INBOX"]:
                try:
                    imap.select(mailbox, readonly=True)
                    status, msg_data = imap.fetch(message_id, "(RFC822)")
                    if status == "OK" and msg_data and msg_data[0]:
                        raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                        return _parse_message(raw, message_id, self._account_id)
                except Exception:
                    continue
            raise ValueError(f"Message {message_id} not found in Gmail")
        finally:
            try:
                imap.logout()
            except Exception:
                pass


def build_gmail_imap_provider(account_id: str) -> "GmailImapProvider | None":
    """Build Gmail IMAP provider from vault-stored app password. Returns None if not found."""
    from ..connectors.store import ConnectorStore
    store = ConnectorStore()
    acc = store.get_account(account_id)
    if not acc or acc.get("provider") != "gmail":
        return None
    token_str = store._get_token(account_id)
    if not token_str:
        return None
    try:
        creds = json.loads(token_str)
        # Only IMAP accounts have app_password
        if "app_password" not in creds:
            return None
        return GmailImapProvider(
            email_addr=creds["email"],
            app_password=creds["app_password"],
            account_id=account_id,
        )
    except Exception:
        return None
