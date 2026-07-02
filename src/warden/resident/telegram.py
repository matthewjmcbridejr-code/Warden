"""Telegram polling transport for the resident agent.

Adapts marius/integrations/telegram_bot.py's getUpdates approach but uses
raw HTTP polling (via urllib, no python-telegram-bot dependency) so the
resident agent has no hard dependency on that library, and persists the
update offset via state.py (survives restarts).

Allowlist by user id / chat id: anything not on the allowlist is rejected
silently (a denial is still logged to the audit trail, but the allowlist
contents are never echoed back to the sender or logged verbatim).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from . import config as config_mod
from .agent import ResidentAgent
from .messages import InboundMessage
from .state import ResidentState, get_state

logger = logging.getLogger("warden.resident.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_POLL_TIMEOUT = 25  # long-poll seconds
MAX_BACKOFF_SECONDS = 60


class TelegramTransport:
    def __init__(
        self,
        cfg: Optional[config_mod.ResidentConfig] = None,
        state: Optional[ResidentState] = None,
        agent: Optional[ResidentAgent] = None,
    ) -> None:
        self.cfg = cfg or config_mod.load_config()
        self.state = state or get_state(self.cfg.resident_db_path)
        self.agent = agent or ResidentAgent(cfg=self.cfg, state=self.state)
        self._backoff = 1

    # -- authorization --------------------------------------------------------

    def is_allowed(self, user_id: Optional[int], chat_id: Optional[int]) -> bool:
        allowed_users = self.cfg.telegram_allowed_user_ids
        allowed_chats = self.cfg.telegram_allowed_chat_ids
        if not allowed_users and not allowed_chats:
            # No allowlist configured at all — deny everything by default (fail closed).
            return False
        if user_id is not None and user_id in allowed_users:
            return True
        if chat_id is not None and chat_id in allowed_chats:
            return True
        return False

    def _reject(self, user_id: Optional[int], chat_id: Optional[int]) -> None:
        # Never log/echo allowlist contents — only that a rejection happened.
        self.state.audit("telegram_rejected", {"user_id": user_id, "chat_id": chat_id})
        logger.warning("Rejected unauthorized Telegram sender (user_id/chat_id redacted from allowlist context)")

    # -- HTTP -------------------------------------------------------------------

    def _api_url(self, method: str) -> str:
        token = self.cfg.telegram_bot_token
        return f"{TELEGRAM_API_BASE}/bot{token}/{method}"

    def _call(self, method: str, params: dict[str, Any], timeout: float = 30.0) -> dict:
        url = self._api_url(method)
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read())

    def get_updates(self, offset: int, timeout: int = DEFAULT_POLL_TIMEOUT) -> list[dict]:
        result = self._call("getUpdates", {"offset": offset, "timeout": timeout})
        return result.get("result", []) if result.get("ok") else []

    def send_message(self, chat_id: int, text: str) -> None:
        try:
            self._call("sendMessage", {"chat_id": chat_id, "text": text}, timeout=15)
        except Exception as exc:
            logger.warning("Failed to send Telegram message: %s", config_mod.redact_secrets(str(exc)))

    # -- update processing --------------------------------------------------------

    def process_update(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        text = message.get("text")
        if not text:
            return
        chat = message.get("chat", {})
        sender = message.get("from", {})
        chat_id = chat.get("id")
        user_id = sender.get("id")

        if not self.is_allowed(user_id, chat_id):
            self._reject(user_id, chat_id)
            return

        inbound = InboundMessage(
            text=text, user_id=user_id, chat_id=chat_id, transport="telegram",
            update_id=update.get("update_id"), raw={},
        )
        outbound = self.agent.handle(inbound)
        if chat_id is not None:
            self.send_message(chat_id, outbound.text)

    # -- polling loop --------------------------------------------------------

    def poll_once(self) -> int:
        """Fetch and process one batch of updates. Returns count processed.
        Persists offset after each successful batch; retries with backoff on
        network errors."""
        offset = self.state.get_offset("telegram")
        try:
            updates = self.get_updates(offset)
            self._backoff = 1
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Telegram poll failed (retrying with backoff): %s", config_mod.redact_secrets(str(exc)))
            time.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, MAX_BACKOFF_SECONDS)
            return 0

        for update in updates:
            self.process_update(update)
            self.state.set_offset(update["update_id"] + 1, "telegram")

        return len(updates)

    def run_forever(self) -> None:
        if not self.cfg.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set — refusing to start polling loop.")
        logger.info("Resident Telegram transport starting (dry_run=%s)", self.cfg.dry_run)
        while True:
            try:
                self.poll_once()
            except Exception as exc:
                logger.error("Unhandled polling error: %s", config_mod.redact_secrets(str(exc)))
                time.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, MAX_BACKOFF_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    transport = TelegramTransport()
    transport.run_forever()


if __name__ == "__main__":
    main()
