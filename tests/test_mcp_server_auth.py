"""Auth acceptance for the Brain MCP HTTP server: legacy shared token, any
active per-client token (warden.mcp_tokens), or an OAuth-issued token are all
unified behind OAuthProvider.load_access_token() (src/warden/mcp_oauth.py) —
this is what the SDK's RequireAuthMiddleware calls to gate the /mcp route.
No live server needed. Full OAuth-flow coverage lives in test_mcp_oauth.py;
this file focuses on the unification of the three token kinds."""
import importlib

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def oauth_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_MCP_OAUTH_ROOT", str(tmp_path / "mcp_oauth"))
    monkeypatch.setenv("WARDEN_MCP_CLIENTS_ROOT", str(tmp_path / "mcp_clients"))
    import src.warden.mcp_oauth as mod
    importlib.reload(mod)
    return mod


async def test_legacy_shared_token_still_works(oauth_env, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_TOKEN", "legacy-shared-token")
    provider = oauth_env.OAuthProvider()
    assert await provider.load_access_token("legacy-shared-token") is not None


async def test_wrong_shared_token_rejected_without_client_tokens(oauth_env, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_TOKEN", "legacy-shared-token")
    provider = oauth_env.OAuthProvider()
    assert await provider.load_access_token("wrong") is None


async def test_per_client_token_accepted(oauth_env):
    from src.warden import mcp_tokens
    _, raw_token = mcp_tokens.issue_token("claude_app")
    provider = oauth_env.OAuthProvider()
    assert await provider.load_access_token(raw_token) is not None


async def test_revoked_per_client_token_rejected(oauth_env):
    from src.warden import mcp_tokens
    client_id, raw_token = mcp_tokens.issue_token("codex_app")
    mcp_tokens.revoke_token(client_id)
    provider = oauth_env.OAuthProvider()
    assert await provider.load_access_token(raw_token) is None


async def test_empty_presented_token_rejected(oauth_env, monkeypatch):
    monkeypatch.setenv("WARDEN_BRAIN_TOKEN", "legacy-shared-token")
    provider = oauth_env.OAuthProvider()
    assert await provider.load_access_token("") is None
