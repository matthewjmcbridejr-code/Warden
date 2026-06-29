"""OAuth2 connection flow helpers for Gmail and Outlook connectors."""
from __future__ import annotations
import os
import secrets
from typing import Any

_STATES: dict[str, dict] = {}  # state -> {provider, redirect_uri, ...}


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
