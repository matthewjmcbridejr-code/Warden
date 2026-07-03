"""Secret redaction and config loading tests."""
import os
from unittest.mock import patch

from src.warden.resident import config as config_mod


def test_redact_secrets_telegram_token():
    text = "token is 123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx please don't log"
    redacted = config_mod.redact_secrets(text)
    assert "AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" not in redacted
    assert "[REDACTED_TOKEN]" in redacted


def test_redact_secrets_bearer_header():
    text = "Authorization: Bearer sk-abcdef1234567890"
    redacted = config_mod.redact_secrets(text)
    assert "sk-abcdef1234567890" not in redacted


def test_redact_secrets_key_value_pair():
    text = 'api_key: "sk-verysecret123"'
    redacted = config_mod.redact_secrets(text)
    assert "sk-verysecret123" not in redacted
    assert "REDACTED" in redacted


def test_redact_secrets_password_field():
    text = "password=hunter2andmore"
    redacted = config_mod.redact_secrets(text)
    assert "hunter2andmore" not in redacted


def test_redact_secrets_empty_string_is_noop():
    assert config_mod.redact_secrets("") == ""


def test_redact_dict_masks_secret_keys():
    data = {"token": "abc123", "safe_field": "hello"}
    out = config_mod.redact_dict(data)
    assert out["token"] == "[REDACTED]"
    assert out["safe_field"] == "hello"


def test_load_config_defaults():
    with patch.dict(os.environ, {}, clear=True):
        cfg = config_mod.load_config()
        assert cfg.email_mode == "disabled"
        assert cfg.email_dry_run is True
        assert cfg.model_profile == "fast"
        assert cfg.warden_private_base_url == "http://127.0.0.1:8125"
        assert cfg.enable_deep_synthesis is False


def test_load_config_reads_env_overrides():
    env = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_ALLOWED_USER_IDS": "1,2,3",
        "EMAIL_MODE": "mock",
        "RESIDENT_MAX_CONTEXT_ITEMS": "12",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = config_mod.load_config()
        assert cfg.telegram_bot_token == "tok"
        assert cfg.telegram_allowed_user_ids == [1, 2, 3]
        assert cfg.email_mode == "mock"
        assert cfg.max_context_items == 12


def test_sandbox_domain_guard():
    assert config_mod.is_sandbox_domain("unlck.shop") is True
    assert config_mod.is_sandbox_domain("UNLCK.SHOP") is True
    assert config_mod.is_sandbox_domain("example.com") is False
    assert config_mod.is_sandbox_domain("") is False
