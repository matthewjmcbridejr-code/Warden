"""Email adapter wrapping mail/gmail.py + mail/gmail_imap.py.

Modes (from config.email_mode):
  disabled — default. All operations return a clear "email disabled" response.
  mock     — in-memory fake inbox for tests/demos, no network calls.
  gmail    — Gmail API (OAuth) via mail/gmail.py.
  imap     — Gmail IMAP (app password) via mail/gmail_imap.py.

Sends are never performed directly — draft() always stages a draft, and
send() only proceeds if EMAIL_MODE allows it AND an approval has been
granted (checked by the caller via approvals.py before invoking send()).

Incremental summarize() tracks last_seen_message_id per account so repeated
"check my email" calls only surface genuinely new messages, capped at N.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_SUMMARY_CAP = 10
URGENT_KEYWORDS = ("urgent", "asap", "immediately", "deadline", "action required", "past due")


@dataclass
class DraftResult:
    ok: bool
    to: str
    subject: str
    body: str
    draft_id: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SendResult:
    ok: bool
    reason: str
    to: str = ""
    subject: str = ""


class _MockMailbox:
    """Deterministic in-memory mailbox for EMAIL_MODE=mock."""

    def __init__(self) -> None:
        self.messages = [
            {
                "id": "mock-1",
                "from_addr": "billing@example.com",
                "subject": "Invoice due — action required",
                "date": "2026-06-30T09:00:00+00:00",
                "snippet": "Your invoice is past due, please remit payment ASAP.",
            },
            {
                "id": "mock-2",
                "from_addr": "team@example.com",
                "subject": "Weekly update",
                "date": "2026-06-29T14:00:00+00:00",
                "snippet": "Here is the weekly status update, nothing urgent.",
            },
        ]

    def search(self, query: str, limit: int) -> list[dict]:
        q = query.lower().strip()
        if not q:
            return self.messages[:limit]
        return [m for m in self.messages if q in m["subject"].lower() or q in m["snippet"].lower()][:limit]

    def list_new(self, since_id: Optional[str], limit: int) -> list[dict]:
        if since_id is None:
            return self.messages[:limit]
        ids = [m["id"] for m in self.messages]
        if since_id in ids:
            idx = ids.index(since_id)
            return self.messages[:idx][:limit]
        return self.messages[:limit]


class EmailAdapter:
    def __init__(self, config, account_id: str = "default") -> None:
        self.config = config
        self.account_id = account_id
        self._mock = _MockMailbox()
        self._last_seen_message_id: Optional[str] = None

    @property
    def mode(self) -> str:
        return (self.config.email_mode or "disabled").lower()

    def _disabled_response(self) -> dict:
        return {
            "ok": False,
            "short_summary": "Email is disabled (EMAIL_MODE=disabled). Set EMAIL_MODE=mock|gmail|imap to enable.",
            "key_fields": {"mode": self.mode},
        }

    # -- summarize ---------------------------------------------------------

    def summarize(self, limit: int = DEFAULT_SUMMARY_CAP) -> dict:
        limit = max(1, min(limit, DEFAULT_SUMMARY_CAP))
        if self.mode == "disabled":
            return self._disabled_response()

        if self.mode == "mock":
            new = self._mock.list_new(self._last_seen_message_id, limit)
            if new:
                self._last_seen_message_id = new[0]["id"]
            return {
                "ok": True,
                "short_summary": f"{len(new)} new message(s)." if new else "No new messages.",
                "key_fields": {"count": len(new), "mode": "mock"},
                "raw": new,
            }

        provider = self._build_provider()
        if provider is None:
            return {
                "ok": False,
                "short_summary": f"Email mode={self.mode} but no account configured/connected.",
                "key_fields": {"mode": self.mode},
            }
        try:
            summaries = provider.search("", limit=limit)
            items = [s.to_dict() for s in summaries]
            if items:
                self._last_seen_message_id = items[0].get("id")
            return {
                "ok": True,
                "short_summary": f"{len(items)} message(s) fetched.",
                "key_fields": {"count": len(items), "mode": self.mode},
                "raw": items,
            }
        except Exception as exc:
            return {"ok": False, "short_summary": f"Email fetch failed: {exc}", "key_fields": {"mode": self.mode}}

    # -- find urgent ---------------------------------------------------------

    def find_urgent(self, limit: int = DEFAULT_SUMMARY_CAP) -> dict:
        base = self.summarize(limit=DEFAULT_SUMMARY_CAP)
        if not base.get("ok"):
            return base
        raw = base.get("raw") or []
        urgent = [
            m for m in raw
            if any(k in (m.get("subject", "") + " " + m.get("snippet", "")).lower() for k in URGENT_KEYWORDS)
        ][:limit]
        return {
            "ok": True,
            "short_summary": f"{len(urgent)} urgent message(s) found." if urgent else "No urgent messages found.",
            "key_fields": {"count": len(urgent)},
            "raw": urgent,
        }

    # -- search ---------------------------------------------------------------

    def search(self, query: str, limit: int = DEFAULT_SUMMARY_CAP) -> dict:
        limit = max(1, min(limit, DEFAULT_SUMMARY_CAP))
        if self.mode == "disabled":
            return self._disabled_response()
        if self.mode == "mock":
            results = self._mock.search(query, limit)
            return {
                "ok": True,
                "short_summary": f"{len(results)} match(es) for {query!r}.",
                "key_fields": {"count": len(results)},
                "raw": results,
            }
        provider = self._build_provider()
        if provider is None:
            return {"ok": False, "short_summary": "No account configured/connected.", "key_fields": {"mode": self.mode}}
        try:
            summaries = provider.search(query, limit=limit)
            items = [s.to_dict() for s in summaries]
            return {
                "ok": True,
                "short_summary": f"{len(items)} match(es) for {query!r}.",
                "key_fields": {"count": len(items)},
                "raw": items,
            }
        except Exception as exc:
            return {"ok": False, "short_summary": f"Search failed: {exc}", "key_fields": {}}

    # -- draft (never sends) ----------------------------------------------------

    def draft(self, to: str, subject: str, body: str) -> DraftResult:
        """Stage a draft. Never sends regardless of mode."""
        draft_id = f"draft-{abs(hash((to, subject, body))) % 100000}"
        return DraftResult(ok=True, to=to, subject=subject, body=body, draft_id=draft_id)

    # -- send (gated) ---------------------------------------------------------

    def send(self, to: str, subject: str, body: str, *, approved: bool) -> SendResult:
        """Send only if EMAIL_MODE allows sending AND approval has been granted.

        This adapter never implements a live send path for gmail/imap providers
        (both are read-only in this codebase) — send always returns a dry-run
        / not-implemented response even when approved, to avoid silently
        pretending to send mail that never leaves the system.
        """
        if self.mode == "disabled":
            return SendResult(ok=False, reason="email disabled (EMAIL_MODE=disabled)", to=to, subject=subject)
        if not approved:
            return SendResult(ok=False, reason="send blocked: requires approval", to=to, subject=subject)
        if self.config.email_dry_run:
            return SendResult(ok=False, reason="dry-run: send suppressed (EMAIL_DRY_RUN=true)", to=to, subject=subject)
        return SendResult(
            ok=False,
            reason="executor not implemented: no live send path wired for this provider",
            to=to,
            subject=subject,
        )

    # -- provider construction --------------------------------------------------

    def _build_provider(self):
        try:
            if self.mode == "gmail":
                from ..mail.gmail import build_gmail_provider
                return build_gmail_provider(self.account_id)
            if self.mode == "imap":
                from ..mail.gmail_imap import build_gmail_imap_provider
                return build_gmail_imap_provider(self.account_id)
        except Exception:
            return None
        return None
