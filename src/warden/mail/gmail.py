"""Gmail provider — read-only via Gmail API using stored OAuth tokens."""
from __future__ import annotations
import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .base import MailProvider
from .models import AttachmentMeta, MailMessage, MailMessageSummary

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://www.googleapis.com/gmail/v1/users/me"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Injected in tests
_http_client = None  # callable(url, method, headers, body) -> (status, dict)


def set_http_client(fn) -> None:
    """Override HTTP client for testing."""
    global _http_client
    _http_client = fn


def _http_get(url: str, headers: dict) -> dict:
    if _http_client is not None:
        return _http_client("GET", url, headers, None)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise TokenExpiredError("Token expired or revoked") from e
        raise GmailAPIError(f"HTTP {e.code}: {body}") from e


def _http_post(url: str, data: bytes, headers: dict) -> dict:
    if _http_client is not None:
        return _http_client("POST", url, headers, data)
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise GmailAPIError(f"HTTP {e.code}: {body}") from e


class TokenExpiredError(Exception):
    pass


class GmailAPIError(Exception):
    pass


def _sanitize_text(text: str, max_len: int = 8000) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    return text[:max_len]


def _snippet(text: str, max_len: int = 200) -> str:
    return _sanitize_text(text.replace("\n", " ").replace("\r", "").strip(), max_len)


def _base64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


class GmailProvider(MailProvider):
    """Gmail read-only provider using stored access_token/refresh_token."""

    def __init__(self, account_id: str, access_token: str, refresh_token: str = ""):
        self._account_id = account_id
        self._access_token = access_token
        self._refresh_token = refresh_token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            raise TokenExpiredError("No refresh token available")
        # Warden supports credentials stored in its local connector vault as
        # well as environment variables. Using only getenv here made a
        # successfully connected mailbox fail as soon as its first one-hour
        # access token expired.
        from ..connectors.oauth import get_provider_credentials
        client_id, client_secret = get_provider_credentials("gmail")
        if not client_id:
            raise TokenExpiredError("Gmail OAuth client is not configured")
        payload = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode()
        result = _http_post(GOOGLE_TOKEN_URL, payload,
                            {"Content-Type": "application/x-www-form-urlencoded"})
        if "access_token" in result:
            self._access_token = result["access_token"]
            self._persist_refreshed_token(result)
        else:
            raise TokenExpiredError("Token refresh failed")

    def _persist_refreshed_token(self, result: dict) -> None:
        """Persist the rotated access token while retaining the refresh token."""
        from ..connectors.store import ConnectorStore

        store = ConnectorStore()
        token_str = store._get_token(self._account_id)
        try:
            stored = json.loads(token_str or "{}")
        except Exception:
            stored = {}
        stored.update({
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_in": result.get("expires_in"),
            "token_type": result.get("token_type", stored.get("token_type", "Bearer")),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        })
        store._store_token(self._account_id, json.dumps(stored))

    def check_connection(self) -> bool:
        try:
            _http_get(f"{GMAIL_API_BASE}/profile", self._auth_headers())
            return True
        except TokenExpiredError:
            try:
                self._refresh_access_token()
                return True
            except Exception:
                return False
        except Exception:
            return False

    def search(self, query: str, limit: int = 10) -> list[MailMessageSummary]:
        url = (f"{GMAIL_API_BASE}/messages?"
               f"q={urllib.parse.quote(query)}&maxResults={min(limit, 50)}")
        try:
            data = _http_get(url, self._auth_headers())
        except TokenExpiredError:
            self._refresh_access_token()
            data = _http_get(url, self._auth_headers())

        messages = data.get("messages", [])
        summaries = []
        for m in messages[:limit]:
            try:
                msg_data = _http_get(
                    f"{GMAIL_API_BASE}/messages/{m['id']}?format=metadata"
                    "&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Date",
                    self._auth_headers(),
                )
                summaries.append(_parse_gmail_metadata(msg_data, self._account_id))
            except Exception as e:
                logger.warning("Error fetching Gmail message %s: %s", m.get("id"), e)
        return summaries

    def read_message(self, message_id: str) -> MailMessage:
        try:
            data = _http_get(f"{GMAIL_API_BASE}/messages/{message_id}?format=full",
                             self._auth_headers())
        except TokenExpiredError:
            self._refresh_access_token()
            data = _http_get(f"{GMAIL_API_BASE}/messages/{message_id}?format=full",
                             self._auth_headers())
        return _parse_gmail_full(data, self._account_id)


def _header_value(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _parse_gmail_metadata(data: dict, account_id: str) -> MailMessageSummary:
    headers = data.get("payload", {}).get("headers", [])
    return MailMessageSummary(
        id=data.get("id", ""),
        thread_id=data.get("threadId", ""),
        account_id=account_id,
        provider="gmail",
        from_addr=_header_value(headers, "From"),
        to_addrs=[a.strip() for a in _header_value(headers, "To").split(",") if a.strip()],
        subject=_header_value(headers, "Subject"),
        date=_header_value(headers, "Date"),
        snippet=_snippet(data.get("snippet", "")),
        labels=data.get("labelIds", []),
        has_attachments=_has_attachments(data.get("payload", {})),
    )


def _has_attachments(payload: dict) -> bool:
    for part in payload.get("parts", []):
        if part.get("filename"):
            return True
        if _has_attachments(part):
            return True
    return False


def _extract_body(payload: dict) -> tuple[str, str]:
    """Recursively extract text/plain and text/html body parts."""
    body_text = ""
    body_html = ""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            body_text = _base64url_decode(data).decode("utf-8", errors="replace")
    elif mime == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            body_html = _base64url_decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        pt, ph = _extract_body(part)
        if pt and not body_text:
            body_text = pt
        if ph and not body_html:
            body_html = ph
    return body_text, body_html


def _parse_gmail_full(data: dict, account_id: str) -> MailMessage:
    summary = _parse_gmail_metadata(data, account_id)
    body_text, body_html = _extract_body(data.get("payload", {}))
    body_text = _sanitize_text(body_text)

    attachments = []
    for part in data.get("payload", {}).get("parts", []):
        if part.get("filename"):
            attachments.append(AttachmentMeta(
                filename=part["filename"],
                mime_type=part.get("mimeType", "application/octet-stream"),
                size_bytes=part.get("body", {}).get("size", 0),
            ))

    return MailMessage(
        summary=MailMessageSummary(
            **{**summary.__dict__,
               "snippet": _snippet(body_text or data.get("snippet", ""))},
        ),
        body_text=body_text,
        body_html="",  # never returned via API
        attachments=attachments,
    )


def build_gmail_provider(account_id: str) -> "GmailProvider | None":
    """Build provider from stored vault token. Returns None if not found/expired."""
    from ..connectors.store import ConnectorStore
    store = ConnectorStore()
    token_str = store._get_token(account_id)
    if not token_str:
        return None
    try:
        creds = json.loads(token_str)
        return GmailProvider(
            account_id=account_id,
            access_token=creds.get("access_token", ""),
            refresh_token=creds.get("refresh_token", ""),
        )
    except Exception:
        return None
