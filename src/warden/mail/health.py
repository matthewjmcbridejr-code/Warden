"""Operational health checks for configured mail accounts.

Account records prove only that Warden has a credential reference.  This
module performs a bounded, read-only provider check so callers can distinguish
"configured" from "actually usable" without ever receiving the credential.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Any


_CACHE_LOCK = Lock()
_HEALTH_CACHE: dict[str, tuple[float, str, dict[str, Any]]] = {}


def _cache_ttl_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("WARDEN_MAIL_HEALTH_TTL_SECONDS", "60")))
    except ValueError:
        return 60.0


def _account_signature(account: dict[str, Any]) -> str:
    return "|".join([
        str(account.get("updated_at", "")),
        str(account.get("status", "")),
        "1" if account.get("credential_stored") else "0",
    ])


def _unchecked_health(account: dict[str, Any]) -> dict[str, Any]:
    if not account.get("credential_stored"):
        return {
            "state": "needs_reauth",
            "operational": False,
            "checked_at": None,
            "cached": False,
            "message": "Credential is missing from Warden's private connector vault.",
        }
    if account.get("status") == "needs_reauth":
        return {
            "state": "needs_reauth",
            "operational": False,
            "checked_at": None,
            "cached": False,
            "message": "Credential is saved but marked for reconnection.",
        }
    return {
        "state": "unchecked",
        "operational": None,
        "checked_at": None,
        "cached": False,
        "message": "Credential is saved; live provider access has not been checked.",
    }


def _build_provider(account_id: str, provider_id: str):
    if provider_id == "gmail":
        from .gmail_imap import build_gmail_imap_provider

        provider = build_gmail_imap_provider(account_id)
        if provider is None:
            from .gmail import build_gmail_provider

            provider = build_gmail_provider(account_id)
        return provider
    if provider_id == "icloud":
        from .icloud import build_icloud_provider

        return build_icloud_provider(account_id)
    return None


def check_mail_account(account: dict[str, Any], *, verify_live: bool) -> dict[str, Any]:
    """Return a redacted operational-health record for one account."""
    account_id = str(account.get("account_id", ""))
    provider_id = str(account.get("provider", ""))
    if not account_id:
        return {
            "state": "invalid",
            "operational": False,
            "checked_at": None,
            "cached": False,
            "message": "Account record has no identifier.",
        }

    unchecked = _unchecked_health(account)
    if unchecked["state"] == "needs_reauth" or not verify_live:
        return unchecked

    signature = _account_signature(account)
    now_mono = time.monotonic()
    with _CACHE_LOCK:
        cached = _HEALTH_CACHE.get(account_id)
    if cached and cached[1] == signature and now_mono - cached[0] <= _cache_ttl_seconds():
        return {**cached[2], "cached": True}

    checked_at = datetime.now(timezone.utc).isoformat()
    if provider_id not in {"gmail", "icloud"}:
        result = {
            "state": "unsupported",
            "operational": None,
            "checked_at": checked_at,
            "cached": False,
            "message": f"Live health checks are not implemented for {provider_id or 'this provider'}.",
        }
    else:
        try:
            provider = _build_provider(account_id, provider_id)
            if provider is None:
                result = {
                    "state": "needs_reauth",
                    "operational": False,
                    "checked_at": checked_at,
                    "cached": False,
                    "message": "Credential could not be loaded from Warden's private connector vault.",
                }
            elif provider.check_connection():
                result = {
                    "state": "operational",
                    "operational": True,
                    "checked_at": checked_at,
                    "cached": False,
                    "message": "Read-only mailbox access verified.",
                }
            else:
                result = {
                    "state": "unavailable",
                    "operational": False,
                    "checked_at": checked_at,
                    "cached": False,
                    "message": "Provider connection check failed; reconnect or retry after checking network access.",
                }
        except ValueError as exc:
            # Provider ValueErrors are deliberately written as user-safe auth
            # guidance. Raw protocol errors and credentials are not returned.
            result = {
                "state": "needs_reauth",
                "operational": False,
                "checked_at": checked_at,
                "cached": False,
                "message": str(exc),
            }
        except Exception as exc:
            result = {
                "state": "unavailable",
                "operational": False,
                "checked_at": checked_at,
                "cached": False,
                "message": f"Provider connection check failed ({type(exc).__name__}).",
            }

    with _CACHE_LOCK:
        _HEALTH_CACHE[account_id] = (now_mono, signature, result)
    return result


def check_mail_accounts(
    accounts: list[dict[str, Any]], *, verify_live: bool
) -> list[dict[str, Any]]:
    """Check multiple accounts without multiplying provider timeout latency.

    Each provider check is independently bounded.  Running them concurrently
    matters for operators with several Google/iCloud accounts: agent bootstrap
    latency should be roughly one provider timeout, not one timeout per account.
    Input order is preserved and credentials remain inside provider builders.
    """
    if len(accounts) < 2 or not verify_live:
        return [check_mail_account(account, verify_live=verify_live) for account in accounts]

    try:
        configured_max = int(os.getenv("WARDEN_MAIL_HEALTH_MAX_WORKERS", "8"))
    except ValueError:
        configured_max = 8
    max_workers = max(1, min(len(accounts), configured_max))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="warden-mail-health") as pool:
        futures = [
            pool.submit(check_mail_account, account, verify_live=True)
            for account in accounts
        ]
        return [future.result() for future in futures]


def clear_mail_health_cache() -> None:
    """Test and reconnect hook."""
    with _CACHE_LOCK:
        _HEALTH_CACHE.clear()
