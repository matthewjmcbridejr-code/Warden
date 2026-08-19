"""Integration tests for Group Chat REST & SSE endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient
from src.warden.app import create_app
from src.warden.group_chat import GroupChatStore

app = create_app()
client = TestClient(app)


def test_group_chat_api_lifecycle(tmp_path):
    import src.warden.group_chat
    db_file = tmp_path / "group_chat.sqlite"
    
    orig_init = src.warden.group_chat.GroupChatStore.__init__
    src.warden.group_chat.GroupChatStore.__init__ = lambda self, db_path=db_file: orig_init(self, db_path=db_file)

    try:
        # 1. GET /api/mcharness/chat/conversations -> lists rooms
        resp1 = client.get("/api/mcharness/chat/conversations")
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["ok"] is True
        assert data1["count"] >= 1
        assert data1["conversations"][0]["conversation_id"] == "conv_warden_team"

        # 2. POST /api/mcharness/chat/conversations/{id}/messages -> sends human prompt
        resp2 = client.post(
            "/api/mcharness/chat/conversations/conv_warden_team/messages",
            json={"text": "What are your core capabilities?", "actor_id": "matt"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["ok"] is True
        assert data2["human_event"]["text"] == "What are your core capabilities?"
        assert len(data2["responses"]) == 1
        assert data2["responses"][0]["actor_id"] == "warden"

        # 3. GET /api/mcharness/chat/conversations/{id}/events -> reads event stream history
        resp3 = client.get("/api/mcharness/chat/conversations/conv_warden_team/events")
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["ok"] is True
        assert data3["count"] == 2
        assert [e["actor_display_name"] for e in data3["events"]] == ["Matt", "Warden"]

    finally:
        src.warden.group_chat.GroupChatStore.__init__ = orig_init
