"""OAuth2 connection flow helpers for Gmail and Outlook connectors."""
from __future__ import annotations
import json
import logging
import os
import secrets
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_STATES: dict[str, dict] = {}  # state -> {provider, redirect_uri, ...}

# Injected in tests to skip real HTTP calls
_token_exchanger = None  # callable(provider, code, redirect_uri) -> dict | None


def set_token_exchanger(fn) -> None:
    """Override the token exchange function (for testing)."""
    global _token_exchanger
    _token_exchanger = fn


def _exchange_gmail_token(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for Gmail tokens via Google's token endpoint."""
    client_id = os.getenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.getenv("WARDEN_GOOGLE_OAUTH_CLIENT_SECRET", "")
    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning("Gmail token exchange HTTP error %s: %s", e.code, body)
        return {"error": f"token_exchange_failed", "error_description": body}
    except Exception as exc:
        logger.warning("Gmail token exchange error: %s", exc)
        return {"error": "token_exchange_exception", "error_description": str(exc)}


def _exchange_outlook_token(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for Outlook tokens via Microsoft's token endpoint."""
    client_id = os.getenv("WARDEN_MICROSOFT_OAUTH_CLIENT_ID", "")
    client_secret = os.getenv("WARDEN_MICROSOFT_OAUTH_CLIENT_SECRET", "")
    tenant = "common"
    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": "openid email offline_access Mail.Read",
    }).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning("Outlook token exchange HTTP error %s: %s", e.code, body)
        return {"error": "token_exchange_failed", "error_description": body}
    except Exception as exc:
        logger.warning("Outlook token exchange error: %s", exc)
        return {"error": "token_exchange_exception", "error_description": str(exc)}


def _extract_email_from_token(token_response: dict, provider: str) -> str:
    """Extract user email from token response if available (id_token or email field)."""
    # Some providers return email directly
    if "email" in token_response:
        return token_response["email"]
    # Try to decode the id_token without verification (display only)
    id_token = token_response.get("id_token", "")
    if id_token:
        try:
            parts = id_token.split(".")
            if len(parts) >= 2:
                import base64
                padded = parts[1] + "=="
                payload = json.loads(base64.urlsafe_b64decode(padded).decode())
                return payload.get("email", "")
        except Exception:
            pass
    return ""


def exchange_code_for_token(provider: str, code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for tokens. Uses injected exchanger in tests."""
    if _token_exchanger is not None:
        return _token_exchanger(provider, code, redirect_uri)
    if provider == "gmail":
        return _exchange_gmail_token(code, redirect_uri)
    if provider == "outlook":
        return _exchange_outlook_token(code, redirect_uri)
    return {"error": "unsupported_provider"}


def _gmail_auth_url(state: str, redirect_uri: str) -> str:
    client_id = os.getenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID", "")
    scopes = " ".join([
        "https://www.googleapis.com/auth/gmail.readonly",
        "openid", "email",
    ])
    return (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scopes.replace(' ', '%20')}"
        f"&state={state}"
        f"&access_type=offline"
        f"&prompt=consent"
    )


def _outlook_auth_url(state: str, redirect_uri: str) -> str:
    client_id = os.getenv("WARDEN_MICROSOFT_OAUTH_CLIENT_ID", "")
    scopes = " ".join(["openid", "email", "offline_access", "Mail.Read"])
    tenant = "common"
    return (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scopes.replace(' ', '%20')}"
        f"&state={state}"
        f"&response_mode=query"
    )


def start_oauth_flow(provider: str, base_url: str) -> dict:
    """Begin an OAuth2 authorization flow. Returns {auth_url, state} or {error}."""
    redirect_uri = f"{base_url.rstrip('/')}/api/mcharness/warden/connectors/{provider}/callback"

    if provider == "gmail":
        if not os.getenv("WARDEN_GOOGLE_OAUTH_CLIENT_ID"):
            return {"configured": False, "error": "WARDEN_GOOGLE_OAUTH_CLIENT_ID not set"}
        state = secrets.token_urlsafe(24)
        _STATES[state] = {"provider": provider, "redirect_uri": redirect_uri}
        return {"auth_url": _gmail_auth_url(state, redirect_uri), "state": state, "provider": provider}

    if provider == "outlook":
        if not os.getenv("WARDEN_MICROSOFT_OAUTH_CLIENT_ID"):
            return {"configured": False, "error": "WARDEN_MICROSOFT_OAUTH_CLIENT_ID not set"}
        state = secrets.token_urlsafe(24)
        _STATES[state] = {"provider": provider, "redirect_uri": redirect_uri}
        return {"auth_url": _outlook_auth_url(state, redirect_uri), "state": state, "provider": provider}

    return {"configured": False, "error": f"Unknown provider: {provider}"}


def validate_callback_state(state: str) -> dict | None:
    """Validate the state param from OAuth callback. Returns stored state data or None."""
    return _STATES.pop(state, None)
