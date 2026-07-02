"""Resident agent configuration: env loading and secret redaction.

All resident modules import config from here rather than reading os.environ
directly, so tests can monkeypatch a single source of truth.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _id_list_env(name: str) -> list[int]:
    raw = os.getenv(name, "")
    out: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            continue
    return out


@dataclass
class ResidentConfig:
    telegram_bot_token: str = ""
    telegram_allowed_user_ids: list[int] = field(default_factory=list)
    telegram_allowed_chat_ids: list[int] = field(default_factory=list)
    warden_private_base_url: str = "http://127.0.0.1:8125"
    resident_db_path: str = "_mctable/resident/resident.sqlite"
    dry_run: bool = False
    email_mode: str = "disabled"  # disabled | mock | gmail | imap
    email_provider: str = ""
    email_dry_run: bool = True
    model_profile: str = "fast"  # fast | balanced | deep
    max_context_items: int = 8
    max_response_chars: int = 900
    enable_deep_synthesis: bool = False


def load_config() -> ResidentConfig:
    """Load resident config fresh from the environment. Call once per operation
    (not cached at import time) so tests can monkeypatch os.environ safely."""
    return ResidentConfig(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_allowed_user_ids=_id_list_env("TELEGRAM_ALLOWED_USER_IDS"),
        telegram_allowed_chat_ids=_id_list_env("TELEGRAM_ALLOWED_CHAT_IDS"),
        warden_private_base_url=os.getenv("WARDEN_PRIVATE_BASE_URL", "http://127.0.0.1:8125"),
        resident_db_path=os.getenv("WARDEN_RESIDENT_DB", "_mctable/resident/resident.sqlite"),
        dry_run=_bool_env("WARDEN_RESIDENT_DRY_RUN", False),
        email_mode=os.getenv("EMAIL_MODE", "disabled").strip().lower(),
        email_provider=os.getenv("EMAIL_PROVIDER", ""),
        email_dry_run=_bool_env("EMAIL_DRY_RUN", True),
        model_profile=os.getenv("RESIDENT_MODEL_PROFILE", "fast").strip().lower(),
        max_context_items=_int_env("RESIDENT_MAX_CONTEXT_ITEMS", 8),
        max_response_chars=_int_env("RESIDENT_MAX_RESPONSE_CHARS", 900),
        enable_deep_synthesis=_bool_env("RESIDENT_ENABLE_DEEP_SYNTHESIS", False),
    )


# ---------------------------------------------------------------------------
# Secret redaction — used everywhere logging happens
# ---------------------------------------------------------------------------

_SECRET_KEY_PATTERN = re.compile(
    r"(?i)\b(token|api[_-]?key|secret|password|passwd|auth|cookie|bearer|access[_-]?token|refresh[_-]?token)\b"
)

# Matches "key=value" / "key: value" / "key: 'value'" style pairs whose key
# looks secret-like, redacting only the value.
_KV_PATTERN = re.compile(
    r"(?i)((?:token|api[_-]?key|secret|password|passwd|auth|cookie|bearer|access[_-]?token|refresh[_-]?token)"
    r"\s*[:=]\s*)([\"']?)([^\s\"',}]+)(\2)"
)

# Telegram bot token shape: 123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
_TELEGRAM_TOKEN_PATTERN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")

# Bearer/authorization header values
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/=-]{8,})")


def redact_secrets(text: str) -> str:
    """Best-effort redaction of tokens/keys/passwords/cookies/auth headers from
    a string before it is logged. Never raises."""
    if not text:
        return text
    try:
        out = _TELEGRAM_TOKEN_PATTERN.sub("[REDACTED_TOKEN]", text)
        out = _BEARER_PATTERN.sub(lambda m: m.group(1) + "[REDACTED]", out)
        out = _KV_PATTERN.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]" + m.group(2), out)
        return out
    except Exception:
        return "[REDACTION_ERROR]"


def redact_dict(data: dict) -> dict:
    """Recursively redact values for keys that look secret-like."""
    out: dict = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[k] = redact_dict(v)
        elif isinstance(v, str) and _SECRET_KEY_PATTERN.search(str(k)):
            out[k] = "[REDACTED]"
        elif isinstance(v, str):
            out[k] = redact_secrets(v)
        else:
            out[k] = v
    return out


# Sandbox domain guard — hardcoded per production-safety policy shared with
# src/warden/webstudio/dns_migration.py. Only this domain is treated as a
# disposable sandbox; every other domain requires the approval/migration
# workflow for any DNS or deploy action.
SANDBOX_DOMAINS = frozenset({"unlck.shop"})


def is_sandbox_domain(domain: str) -> bool:
    return (domain or "").strip().lower() in SANDBOX_DOMAINS
