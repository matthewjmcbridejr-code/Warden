"""Unit tests for Agent Mailbox MCP tools (warden_team_*)."""
from __future__ import annotations

import json
from src.warden.brain_mcp_server import (
    warden_team_rooms,
    warden_team_history,
    warden_team_inbox,
    warden_team_send,
    warden_team_ack,
    warden_team_status,
)


def test_mcp_team_mailbox_tools(tmp_path):
    import src.warden.group_chat
    db_file = tmp_path / "group_chat.sqlite"
    
    # Instantiate store with custom db path
    store = src.warden.group_chat.GroupChatStore(db_path=db_file)
    # Monkeypatch default store init
    orig_init = src.warden.group_chat.GroupChatStore.__init__
    src.warden.group_chat.GroupChatStore.__init__ = lambda self, db_path=db_file: orig_init(self, db_path=db_file)

    try:
        # 1. warden_team_rooms
        r_res = json.loads(warden_team_rooms(project="Warden"))
        assert r_res["ok"] is True
        assert r_res["data"]["count"] >= 1

        # 2. warden_team_send
        s_res = json.loads(warden_team_send(message="Settings screen implementation in progress @Codex", project="Warden"))
        assert s_res["ok"] is True
        assert s_res["data"]["event_id"] is not None

        # 3. warden_team_history
        h_res = json.loads(warden_team_history())
        assert h_res["ok"] is True
        assert h_res["data"]["count"] >= 1

        # 4. warden_team_inbox
        i_res = json.loads(warden_team_inbox(agent_id="codex"))
        assert i_res["ok"] is True
        assert i_res["data"]["count"] >= 1

        # 5. warden_team_status
        st_res = json.loads(warden_team_status(status="working", current_task="Settings UX"))
        assert st_res["ok"] is True
        assert st_res["data"]["status"] == "working"

        # 6. warden_team_ack
        ack_res = json.loads(warden_team_ack(read_seq=1))
        assert ack_res["ok"] is True
        assert ack_res["data"]["acknowledged"] is True
    finally:
        src.warden.group_chat.GroupChatStore.__init__ = orig_init
