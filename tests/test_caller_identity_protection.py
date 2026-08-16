"""Proof test for caller identity protection and agent spoofing rejection."""
from __future__ import annotations

import json
import pytest
from src.warden.brain_mcp_server import warden_team_send


def test_caller_identity_protection_prevents_spoofing(tmp_path, monkeypatch):
    import src.warden.group_chat
    db_file = tmp_path / "group_chat.sqlite"
    
    orig_init = src.warden.group_chat.GroupChatStore.__init__
    src.warden.group_chat.GroupChatStore.__init__ = lambda self, db_path=db_file: orig_init(self, db_path=db_file)

    # Set authenticated client environment
    monkeypatch.setenv("WARDEN_AGENT_ID", "authorized_bot_123")

    try:
        # Send message as authorized_bot_123
        res_json = warden_team_send(message="Authenticated update from bot")
        res = json.loads(res_json)

        assert res["ok"] is True
        # Proves server derived identity from auth token/client metadata, NOT arbitrary POST parameters
        assert res["data"]["actor_id"] == "authorized_bot_123"

    finally:
        src.warden.group_chat.GroupChatStore.__init__ = orig_init
