"""Per-client MCP token issue/verify/revoke lifecycle. No live server needed."""
import importlib

import pytest


@pytest.fixture
def tokens_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("WARDEN_MCP_CLIENTS_ROOT", str(tmp_path / "mcp_clients"))
    import src.warden.mcp_tokens as mod
    importlib.reload(mod)
    return mod


def test_issue_returns_client_id_and_raw_token(tokens_mod):
    client_id, raw_token = tokens_mod.issue_token("claude_app")
    assert client_id
    assert raw_token
    assert len(raw_token) >= 32


def test_raw_token_never_persisted_on_disk(tokens_mod, tmp_path):
    client_id, raw_token = tokens_mod.issue_token("codex_app")
    on_disk = tokens_mod._tokens_path().read_text()
    assert raw_token not in on_disk
    assert client_id in on_disk


def test_verify_token_succeeds_for_valid_token(tokens_mod):
    _, raw_token = tokens_mod.issue_token("claude_app")
    record = tokens_mod.verify_token(raw_token)
    assert record is not None
    assert record["name"] == "claude_app"
    assert "token_hash" not in record


def test_verify_token_fails_for_unknown_token(tokens_mod):
    tokens_mod.issue_token("claude_app")
    assert tokens_mod.verify_token("not-a-real-token") is None


def test_verify_token_fails_for_empty_string(tokens_mod):
    assert tokens_mod.verify_token("") is None


def test_verify_token_updates_last_used_at(tokens_mod):
    _, raw_token = tokens_mod.issue_token("claude_app")
    before = tokens_mod.list_clients()[0]
    assert before["last_used_at"] is None
    tokens_mod.verify_token(raw_token)
    after = tokens_mod.list_clients()[0]
    assert after["last_used_at"] is not None


def test_revoke_token_blocks_future_verification(tokens_mod):
    client_id, raw_token = tokens_mod.issue_token("codex_app")
    assert tokens_mod.verify_token(raw_token) is not None
    ok = tokens_mod.revoke_token(client_id)
    assert ok is True
    assert tokens_mod.verify_token(raw_token) is None


def test_revoke_unknown_client_id_returns_false(tokens_mod):
    assert tokens_mod.revoke_token("does-not-exist") is False


def test_list_clients_redacts_token_hash(tokens_mod):
    tokens_mod.issue_token("claude_app")
    clients = tokens_mod.list_clients()
    assert len(clients) == 1
    assert "token_hash" not in clients[0]
    assert clients[0]["name"] == "claude_app"


def test_multiple_clients_independent_tokens(tokens_mod):
    _, claude_token = tokens_mod.issue_token("claude_app")
    _, codex_token = tokens_mod.issue_token("codex_app")
    assert tokens_mod.verify_token(claude_token)["name"] == "claude_app"
    assert tokens_mod.verify_token(codex_token)["name"] == "codex_app"
    assert claude_token != codex_token
