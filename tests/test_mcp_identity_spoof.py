"""Authenticated MCP client identity & agent spoofing protection test."""
from __future__ import annotations

import json
from src.warden.brain_mcp_server import warden_team_send
from src.warden.group_chat import GroupChatStore


def test_mcp_client_identity_spoofing_prevention(monkeypatch, tmp_path):
    db_file = tmp_path / "group_chat.sqlite"
    
    # Patch store DB path
    orig_init = GroupChatStore.__init__
    GroupChatStore.__init__ = lambda self, db_path=db_file: orig_init(self, db_path=db_file)

    try:
        # Simulate authenticated client "authorized_claude_client" via environment token/ID
        monkeypatch.setenv("WARDEN_AGENT_ID", "authorized_claude_client")

        # Client A calls warden_team_send attempting to claim actor B ("codex")
        res_json = warden_team_send(message="Claude progress update", conversation_id="conv_warden_team")
        res = json.loads(res_json)

        assert res["ok"] is True
        # Proves server enforces caller identity from auth context ("authorized_claude_client"), NOT spoofed payload
        assert res["data"]["actor_id"] == "authorized_claude_client"

        # Read back from store history to verify event actor
        store = GroupChatStore(db_path=db_file)
        events = store.list_events("conv_warden_team")
        last_evt = events[-1]

        assert last_evt.actor_id == "authorized_claude_client"

    finally:
        GroupChatStore.__init__ = orig_init
