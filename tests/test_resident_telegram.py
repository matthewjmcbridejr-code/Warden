"""Telegram allowlist authorization + offset persistence tests."""
from unittest.mock import MagicMock, patch

import pytest

from src.warden.resident.config import ResidentConfig
from src.warden.resident.state import ResidentState
from src.warden.resident.telegram import TelegramTransport


@pytest.fixture
def transport(tmp_path):
    cfg = ResidentConfig(
        resident_db_path=str(tmp_path / "resident.sqlite"),
        telegram_bot_token="123456:FAKE",
        telegram_allowed_user_ids=[111],
        telegram_allowed_chat_ids=[222],
    )
    state = ResidentState(cfg.resident_db_path)
    return TelegramTransport(cfg=cfg, state=state)


def test_allowed_user_id_authorized(transport):
    assert transport.is_allowed(user_id=111, chat_id=999) is True


def test_allowed_chat_id_authorized(transport):
    assert transport.is_allowed(user_id=999, chat_id=222) is True


def test_unknown_sender_rejected(transport):
    assert transport.is_allowed(user_id=999, chat_id=999) is False


def test_no_allowlist_configured_fails_closed(tmp_path):
    cfg = ResidentConfig(resident_db_path=str(tmp_path / "r2.sqlite"), telegram_bot_token="x")
    state = ResidentState(cfg.resident_db_path)
    t = TelegramTransport(cfg=cfg, state=state)
    assert t.is_allowed(user_id=1, chat_id=1) is False


def test_process_update_rejects_unauthorized_and_does_not_call_send(transport):
    transport.send_message = MagicMock()
    update = {
        "update_id": 1,
        "message": {"text": "hi", "chat": {"id": 999}, "from": {"id": 999}},
    }
    transport.process_update(update)
    transport.send_message.assert_not_called()


def test_process_update_authorized_calls_agent_and_sends(transport):
    transport.send_message = MagicMock()
    update = {
        "update_id": 1,
        "message": {"text": "/start", "chat": {"id": 222}, "from": {"id": 111}},
    }
    transport.process_update(update)
    transport.send_message.assert_called_once()
    args, _ = transport.send_message.call_args
    assert args[0] == 222
    assert "online" in args[1].lower()


def test_offset_persisted_across_polls(transport):
    assert transport.state.get_offset("telegram") == 0
    with patch.object(transport, "get_updates", return_value=[
        {"update_id": 5, "message": {"text": "/start", "chat": {"id": 222}, "from": {"id": 111}}},
    ]):
        transport.send_message = MagicMock()
        n = transport.poll_once()
    assert n == 1
    assert transport.state.get_offset("telegram") == 6


def test_poll_once_backs_off_on_network_error(transport):
    import urllib.error
    transport._backoff = 1
    with patch.object(transport, "get_updates", side_effect=urllib.error.URLError("network down")):
        with patch("time.sleep") as mock_sleep:
            n = transport.poll_once()
    assert n == 0
    mock_sleep.assert_called_once()
    assert transport._backoff == 2
