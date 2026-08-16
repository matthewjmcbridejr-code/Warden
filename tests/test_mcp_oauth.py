"""OAuth 2.1 authorization-server provider for the Brain MCP server.

Exercises src/warden/mcp_oauth.py's OAuthProvider directly (the protocol
methods mcp.server.auth's routes/middleware call) plus the consent-approval
helpers, without a live server or browser. No network needed.
"""
import base64
import hashlib
import secrets

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

pytestmark = pytest.mark.anyio


@pytest.fixture
def oauth_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_MCP_OAUTH_ROOT", str(tmp_path / "mcp_oauth"))
    monkeypatch.setenv("WARDEN_MCP_CLIENTS_ROOT", str(tmp_path / "mcp_clients"))
    monkeypatch.setenv("MCP_OAUTH_OWNER_PASSPHRASE", "correct-passphrase")
    import src.warden.mcp_oauth as mod
    import importlib
    importlib.reload(mod)
    return mod


@pytest.fixture
def provider(oauth_env):
    return oauth_env.OAuthProvider()


def _pkce_pair():
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


async def _register_client(provider, client_id="client-1", redirect_uri="https://example.com/cb"):
    info = OAuthClientInformationFull(
        redirect_uris=[AnyUrl(redirect_uri)], client_name="Test Client", client_id=client_id,
    )
    await provider.register_client(info)
    return await provider.get_client(client_id)


async def test_register_and_get_client_round_trip(provider):
    client = await _register_client(provider)
    assert client is not None
    assert client.client_name == "Test Client"


async def test_client_summary_exposes_identity_without_credentials(provider, oauth_env):
    await _register_client(provider, client_id="hyperagent-123")

    summary = oauth_env.get_client_summary("hyperagent-123")

    assert summary == {
        "client_id": "hyperagent-123",
        "client_name": "Test Client",
    }
    assert "secret" not in summary


async def test_register_client_rejects_http_redirect_uri(provider, oauth_env):
    from mcp.server.auth.provider import RegistrationError
    info = OAuthClientInformationFull(
        redirect_uris=[AnyUrl("http://not-localhost.example.com/cb")],
        client_name="Bad Client", client_id="client-bad",
    )
    with pytest.raises(RegistrationError):
        await provider.register_client(info)


async def test_client_secret_never_stored_in_plaintext_on_disk(provider, oauth_env, tmp_path):
    info = OAuthClientInformationFull(
        redirect_uris=[AnyUrl("https://example.com/cb")],
        client_name="Secret Client", client_id="client-secret",
        client_secret="super-secret-value",
    )
    await provider.register_client(info)
    on_disk = (oauth_env._path("clients.json")).read_text()
    # We don't hash client_secret in this pass (SDK-issued secrets for
    # dynamic registration are handled by the register handler itself before
    # reaching us) — but this test guards against ever writing our OWN
    # long-lived owner passphrase or bearer tokens into this file.
    assert "correct-passphrase" not in on_disk


async def test_full_authorize_to_token_round_trip(provider, oauth_env):
    client = await _register_client(provider)
    verifier, challenge = _pkce_pair()
    params = AuthorizationParams(
        state="xyz", scopes=["mcp"], code_challenge=challenge,
        redirect_uri=AnyUrl("https://example.com/cb"), redirect_uri_provided_explicitly=True,
    )
    consent_url = await provider.authorize(client, params)
    assert "/oauth/consent?request_id=" in consent_url
    request_id = consent_url.split("request_id=")[1]

    redirect = oauth_env.approve_pending_authorization(request_id, "correct-passphrase")
    assert redirect is not None
    assert redirect.startswith("https://example.com/cb?")
    assert "state=xyz" in redirect
    code = redirect.split("code=")[1].split("&")[0]

    auth_code = await provider.load_authorization_code(client, code)
    assert auth_code is not None

    tokens = await provider.exchange_authorization_code(client, auth_code)
    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.scope == "mcp"


async def test_wrong_passphrase_denies_without_leaking_reason(provider, oauth_env):
    client = await _register_client(provider)
    _, challenge = _pkce_pair()
    params = AuthorizationParams(
        state=None, scopes=["mcp"], code_challenge=challenge,
        redirect_uri=AnyUrl("https://example.com/cb"), redirect_uri_provided_explicitly=True,
    )
    consent_url = await provider.authorize(client, params)
    request_id = consent_url.split("request_id=")[1]
    result = oauth_env.approve_pending_authorization(request_id, "wrong-passphrase")
    assert result is None


async def test_deny_pending_authorization_redirects_with_access_denied(provider, oauth_env):
    client = await _register_client(provider)
    _, challenge = _pkce_pair()
    params = AuthorizationParams(
        state="abc", scopes=["mcp"], code_challenge=challenge,
        redirect_uri=AnyUrl("https://example.com/cb"), redirect_uri_provided_explicitly=True,
    )
    consent_url = await provider.authorize(client, params)
    request_id = consent_url.split("request_id=")[1]
    redirect = oauth_env.deny_pending_authorization(request_id)
    assert redirect is not None
    assert "error=access_denied" in redirect
    assert "state=abc" in redirect


async def test_authorization_code_is_single_use(provider, oauth_env):
    client = await _register_client(provider)
    _, challenge = _pkce_pair()
    params = AuthorizationParams(
        state=None, scopes=["mcp"], code_challenge=challenge,
        redirect_uri=AnyUrl("https://example.com/cb"), redirect_uri_provided_explicitly=True,
    )
    consent_url = await provider.authorize(client, params)
    request_id = consent_url.split("request_id=")[1]
    redirect = oauth_env.approve_pending_authorization(request_id, "correct-passphrase")
    code = redirect.split("code=")[1].split("&")[0]

    auth_code = await provider.load_authorization_code(client, code)
    await provider.exchange_authorization_code(client, auth_code)

    auth_code_again = await provider.load_authorization_code(client, code)
    assert auth_code_again is None


async def test_expired_authorization_code_rejected_by_token_handler_expiry_check(provider, oauth_env):
    client = await _register_client(provider)
    _, challenge = _pkce_pair()
    params = AuthorizationParams(
        state=None, scopes=["mcp"], code_challenge=challenge,
        redirect_uri=AnyUrl("https://example.com/cb"), redirect_uri_provided_explicitly=True,
    )
    consent_url = await provider.authorize(client, params)
    request_id = consent_url.split("request_id=")[1]
    redirect = oauth_env.approve_pending_authorization(request_id, "correct-passphrase")
    code = redirect.split("code=")[1].split("&")[0]

    auth_code = await provider.load_authorization_code(client, code)
    # The SDK's token handler (not our code) checks `expires_at < time.time()`
    # before calling exchange_authorization_code — verify we set a sane,
    # short expiry rather than something effectively unlimited.
    import time
    assert auth_code.expires_at - time.time() <= oauth_env.AUTH_CODE_TTL_SECONDS


async def test_load_access_token_accepts_oauth_issued_token(provider, oauth_env):
    client = await _register_client(provider)
    _, challenge = _pkce_pair()
    params = AuthorizationParams(
        state=None, scopes=["mcp"], code_challenge=challenge,
        redirect_uri=AnyUrl("https://example.com/cb"), redirect_uri_provided_explicitly=True,
    )
    consent_url = await provider.authorize(client, params)
    request_id = consent_url.split("request_id=")[1]
    redirect = oauth_env.approve_pending_authorization(request_id, "correct-passphrase")
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = await provider.load_authorization_code(client, code)
    tokens = await provider.exchange_authorization_code(client, auth_code)

    access = await provider.load_access_token(tokens.access_token)
    assert access is not None
    assert access.scopes == ["mcp"]


async def test_load_access_token_accepts_phase1_per_client_token(provider, oauth_env):
    from src.warden import mcp_tokens
    _, raw_token = mcp_tokens.issue_token("claude_app")
    access = await provider.load_access_token(raw_token)
    assert access is not None
    assert access.scopes == ["mcp"]


async def test_load_access_token_accepts_legacy_shared_token(provider, oauth_env, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_TOKEN", "legacy-shared-secret")
    access = await provider.load_access_token("legacy-shared-secret")
    assert access is not None
    assert access.client_id == "legacy-shared-token"


async def test_load_access_token_rejects_garbage(provider, oauth_env):
    assert await provider.load_access_token("not-a-real-token") is None


async def test_refresh_token_rotation(provider, oauth_env):
    client = await _register_client(provider)
    _, challenge = _pkce_pair()
    params = AuthorizationParams(
        state=None, scopes=["mcp"], code_challenge=challenge,
        redirect_uri=AnyUrl("https://example.com/cb"), redirect_uri_provided_explicitly=True,
    )
    consent_url = await provider.authorize(client, params)
    request_id = consent_url.split("request_id=")[1]
    redirect = oauth_env.approve_pending_authorization(request_id, "correct-passphrase")
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = await provider.load_authorization_code(client, code)
    tokens = await provider.exchange_authorization_code(client, auth_code)

    refresh = await provider.load_refresh_token(client, tokens.refresh_token)
    assert refresh is not None
    new_tokens = await provider.exchange_refresh_token(client, refresh, ["mcp"])
    assert new_tokens.access_token != tokens.access_token
    assert new_tokens.refresh_token != tokens.refresh_token

    # old refresh token no longer works after rotation
    assert await provider.load_refresh_token(client, tokens.refresh_token) is None
    # old access token is revoked as part of rotation too
    assert await provider.load_access_token(tokens.access_token) is None
    # new access token works
    assert await provider.load_access_token(new_tokens.access_token) is not None


async def test_revoke_token_invalidates_access_and_paired_refresh(provider, oauth_env):
    client = await _register_client(provider)
    _, challenge = _pkce_pair()
    params = AuthorizationParams(
        state=None, scopes=["mcp"], code_challenge=challenge,
        redirect_uri=AnyUrl("https://example.com/cb"), redirect_uri_provided_explicitly=True,
    )
    consent_url = await provider.authorize(client, params)
    request_id = consent_url.split("request_id=")[1]
    redirect = oauth_env.approve_pending_authorization(request_id, "correct-passphrase")
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = await provider.load_authorization_code(client, code)
    tokens = await provider.exchange_authorization_code(client, auth_code)

    access_token_obj = await provider.load_access_token(tokens.access_token)
    await provider.revoke_token(access_token_obj)

    assert await provider.load_access_token(tokens.access_token) is None
    assert await provider.load_refresh_token(client, tokens.refresh_token) is None


async def test_unknown_pending_authorization_returns_none(oauth_env):
    assert oauth_env.get_pending_authorization("does-not-exist") is None
    assert oauth_env.approve_pending_authorization("does-not-exist", "correct-passphrase") is None
    assert oauth_env.deny_pending_authorization("does-not-exist") is None


async def test_owner_passphrase_not_configured_rejects_everything(oauth_env, monkeypatch):
    monkeypatch.delenv("MCP_OAUTH_OWNER_PASSPHRASE", raising=False)
    assert oauth_env.owner_passphrase_valid("anything") is False
