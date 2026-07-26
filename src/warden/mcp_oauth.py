"""OAuth 2.1 authorization server for the Warden Brain MCP server.

Implements `mcp.server.auth.provider.OAuthAuthorizationServerProvider` so
clients that require a full browser-based OAuth flow (ChatGPT connectors,
Notion) can self-register (RFC 7591) and obtain access tokens via the
standard authorization-code + PKCE grant, instead of being handed a
manually-pasted bearer token (which only works for local apps like Claude
Desktop / Codex CLI — see mcp_tokens.py for that simpler Phase 1 path).

Storage follows the same convention as mcp_tokens.py / connectors/store.py:
JSON files under ~/.local/share/warden/mcp_oauth/ (mode 0600), secrets
hashed with SHA-256 before persisting, raw values only ever held in memory
long enough to hand back to the caller once.

Every token kind this server accepts funnels through load_access_token():
  1. an OAuth access token minted by this module, or
  2. a Phase 1 per-client token from mcp_tokens.verify_token(), or
  3. the legacy shared WARDEN_BRAIN_TOKEN env var.
This lets the SDK's own RequireAuthMiddleware be the single enforcement
point for the /mcp route — brain_mcp_server.py no longer needs its own
hand-rolled Bearer check.

Consent: dynamic client registration (/register) is intentionally open per
spec — any app can register itself as a client, same as ChatGPT/Notion do
today against other MCP servers. But actually authorizing (minting a code
for a specific user) requires the caller to know MCP_OAUTH_OWNER_PASSPHRASE,
checked by the consent view in brain_mcp_server.py before calling
approve_pending_authorization() below. Nothing in this module trusts a
request just because it reached /authorize.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Optional

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

AUTH_CODE_TTL_SECONDS = 120  # short-lived, single-use
PENDING_AUTHZ_TTL_SECONDS = 600  # time allowed to complete the consent screen
ACCESS_TOKEN_TTL_SECONDS = 3600  # 1 hour
REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days, rotated on each use
DEFAULT_SCOPE = "mcp"

_LOCK = Lock()


def _vault_root() -> Path:
    base = Path(os.getenv("WARDEN_MCP_OAUTH_ROOT", os.path.expanduser("~/.local/share/warden/mcp_oauth")))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _path(name: str) -> Path:
    return _vault_root() / name


def _now() -> float:
    return time.time()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load(name: str) -> dict:
    path = _path(name)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(name: str, data: dict) -> None:
    path = _path(name)
    path.write_text(json.dumps(data, indent=2))
    try:
        path.chmod(0o600)
    except Exception:
        pass


class OAuthProvider(OAuthAuthorizationServerProvider):
    """Single-owner OAuth 2.1 provider."""

    # -- clients --------------------------------------------------------------

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        with _LOCK:
            clients = _load("clients.json")
        record = clients.get(client_id)
        if record is None:
            return None
        return OAuthClientInformationFull(**record)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.redirect_uris:
            raise RegistrationError(
                error="invalid_client_metadata", error_description="redirect_uris is required"
            )
        for uri in client_info.redirect_uris:
            if str(uri).startswith("http://") and not str(uri).startswith("http://127.0.0.1") \
                    and not str(uri).startswith("http://localhost"):
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description="redirect_uris must use https (except loopback for local testing)",
                )
        with _LOCK:
            clients = _load("clients.json")
            clients[client_info.client_id] = json.loads(client_info.model_dump_json(exclude_none=True))
            _save("clients.json", clients)

    # -- authorize (interactive consent) --------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = uuid.uuid4().hex
        record = {
            "request_id": request_id,
            "client_id": client.client_id,
            "client_name": client.client_name or client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "code_challenge": params.code_challenge,
            "scopes": params.scopes or [DEFAULT_SCOPE],
            "state": params.state,
            "resource": params.resource,
            "expires_at": _now() + PENDING_AUTHZ_TTL_SECONDS,
        }
        with _LOCK:
            pending = _load("pending_authorizations.json")
            pending[request_id] = record
            _save("pending_authorizations.json", pending)
        issuer = os.getenv("MCP_OAUTH_ISSUER_URL", "https://mcp.mctable.online")
        return f"{issuer}/oauth/consent?request_id={request_id}"

    # -- authorization codes ---------------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        code_hash = _hash(authorization_code)
        with _LOCK:
            codes = _load("auth_codes.json")
        record = codes.get(code_hash)
        if record is None:
            return None
        return AuthorizationCode(
            code=authorization_code,
            client_id=record["client_id"],
            scopes=record["scopes"],
            expires_at=record["expires_at"],
            code_challenge=record["code_challenge"],
            redirect_uri=AnyUrl(record["redirect_uri"]),
            redirect_uri_provided_explicitly=record["redirect_uri_provided_explicitly"],
            resource=record.get("resource"),
            subject=record.get("subject"),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        code_hash = _hash(authorization_code.code)
        with _LOCK:
            codes = _load("auth_codes.json")
            record = codes.pop(code_hash, None)  # single-use: delete on exchange
            _save("auth_codes.json", codes)
        if record is None:
            raise TokenError(error="invalid_grant", error_description="authorization code already used")

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = _now()
        access_hash = _hash(access_token)
        refresh_hash = _hash(refresh_token)

        with _LOCK:
            tokens = _load("tokens.json")
            tokens[access_hash] = {
                "token_type": "access",
                "client_id": client.client_id,
                "scopes": authorization_code.scopes,
                "expires_at": now + ACCESS_TOKEN_TTL_SECONDS,
                "paired_token_hash": refresh_hash,
                "subject": authorization_code.subject or "operator",
            }
            tokens[refresh_hash] = {
                "token_type": "refresh",
                "client_id": client.client_id,
                "scopes": authorization_code.scopes,
                "expires_at": now + REFRESH_TOKEN_TTL_SECONDS,
                "paired_token_hash": access_hash,
                "subject": authorization_code.subject or "operator",
            }
            _save("tokens.json", tokens)

        return OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(authorization_code.scopes),
        )

    # -- refresh tokens ---------------------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        with _LOCK:
            tokens = _load("tokens.json")
        record = tokens.get(_hash(refresh_token))
        if record is None or record.get("token_type") != "refresh":
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=record["client_id"],
            scopes=record["scopes"],
            expires_at=int(record["expires_at"]),
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        old_refresh_hash = _hash(refresh_token.token)
        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        now = _now()
        new_access_hash = _hash(new_access)
        new_refresh_hash = _hash(new_refresh)

        with _LOCK:
            tokens = _load("tokens.json")
            old_record = tokens.pop(old_refresh_hash, None)
            if old_record is not None:
                # revoke the access token paired with the old refresh token too
                tokens.pop(old_record.get("paired_token_hash", ""), None)
            tokens[new_access_hash] = {
                "token_type": "access",
                "client_id": client.client_id,
                "scopes": scopes,
                "expires_at": now + ACCESS_TOKEN_TTL_SECONDS,
                "paired_token_hash": new_refresh_hash,
                "subject": refresh_token.subject or "operator",
            }
            tokens[new_refresh_hash] = {
                "token_type": "refresh",
                "client_id": client.client_id,
                "scopes": scopes,
                "expires_at": now + REFRESH_TOKEN_TTL_SECONDS,
                "paired_token_hash": new_access_hash,
                "subject": refresh_token.subject or "operator",
            }
            _save("tokens.json", tokens)

        return OAuthToken(
            access_token=new_access,
            refresh_token=new_refresh,
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
        )

    # -- access token verification (unifies all 3 token kinds) -----------------

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        # 1. OAuth-issued access tokens minted by this provider.
        with _LOCK:
            tokens = _load("tokens.json")
        record = tokens.get(_hash(token))
        if record is not None and record.get("token_type") == "access":
            if record["expires_at"] < _now():
                return None
            return AccessToken(
                token=token,
                client_id=record["client_id"],
                scopes=record["scopes"],
                expires_at=int(record["expires_at"]),
                subject=record.get("subject"),
            )

        # 2. Phase 1 per-client bearer tokens (Claude Desktop / Codex CLI).
        try:
            from .mcp_tokens import verify_token
            client_record = verify_token(token)
        except Exception:
            client_record = None
        if client_record is not None:
            return AccessToken(
                token=token,
                client_id=client_record.get("client_id", "legacy-client"),
                scopes=[DEFAULT_SCOPE],
                expires_at=None,
                subject="operator",
            )

        # 3. Legacy shared token.
        legacy = os.getenv("WARDEN_BRAIN_TOKEN", "")
        if legacy and token == legacy:
            return AccessToken(
                token=token, client_id="legacy-shared-token", scopes=[DEFAULT_SCOPE], expires_at=None, subject="operator",
            )

        return None

    # -- revocation -------------------------------------------------------------

    async def revoke_token(self, token) -> None:  # token: AccessToken | RefreshToken
        token_hash = _hash(token.token)
        with _LOCK:
            tokens = _load("tokens.json")
            record = tokens.pop(token_hash, None)
            if record is not None:
                tokens.pop(record.get("paired_token_hash", ""), None)
                _save("tokens.json", tokens)


# ---------------------------------------------------------------------------
# Consent screen helpers — called by brain_mcp_server.py's /oauth/consent
# routes. Nothing above this line trusts an unauthenticated caller; these
# two functions are the only path that can turn a pending authorization
# into a real code, and both require MCP_OAUTH_OWNER_PASSPHRASE.
# ---------------------------------------------------------------------------

def get_pending_authorization(request_id: str) -> Optional[dict]:
    with _LOCK:
        pending = _load("pending_authorizations.json")
    record = pending.get(request_id)
    if record is None or record["expires_at"] < _now():
        return None
    return record


def owner_passphrase_valid(passphrase: str) -> bool:
    expected = os.getenv("MCP_OAUTH_OWNER_PASSPHRASE", "")
    return bool(expected) and secrets.compare_digest(passphrase, expected)


def approve_pending_authorization(request_id: str, passphrase: str) -> Optional[str]:
    """Validate passphrase + pending request, mint a real auth code, return the
    redirect URL with ?code=...&state=... — or None if passphrase/request is invalid
    (caller should redirect with error=access_denied without saying which failed)."""
    if not owner_passphrase_valid(passphrase):
        return None
    with _LOCK:
        pending = _load("pending_authorizations.json")
        record = pending.pop(request_id, None)
        _save("pending_authorizations.json", pending)
    if record is None or record["expires_at"] < _now():
        return None

    code = secrets.token_urlsafe(32)
    with _LOCK:
        codes = _load("auth_codes.json")
        codes[_hash(code)] = {
            "client_id": record["client_id"],
            "scopes": record["scopes"],
            "expires_at": _now() + AUTH_CODE_TTL_SECONDS,
            "code_challenge": record["code_challenge"],
            "redirect_uri": record["redirect_uri"],
            "redirect_uri_provided_explicitly": record["redirect_uri_provided_explicitly"],
            "resource": record.get("resource"),
            "subject": "operator",
        }
        _save("auth_codes.json", codes)

    from mcp.server.auth.provider import construct_redirect_uri
    return construct_redirect_uri(record["redirect_uri"], code=code, state=record.get("state"))


def deny_pending_authorization(request_id: str) -> Optional[str]:
    """Discard the pending request and return the redirect URL with error=access_denied."""
    with _LOCK:
        pending = _load("pending_authorizations.json")
        record = pending.pop(request_id, None)
        _save("pending_authorizations.json", pending)
    if record is None:
        return None
    from mcp.server.auth.provider import construct_redirect_uri
    return construct_redirect_uri(
        record["redirect_uri"], error="access_denied", state=record.get("state")
    )
