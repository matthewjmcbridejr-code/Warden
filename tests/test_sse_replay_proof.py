"""Deterministic proof for SSE event replay and duplicate prevention."""
from __future__ import annotations

import json
from src.warden.group_chat import GroupChatStore, ChatEvent


def test_sse_replay_and_zero_duplicates(tmp_path):
    db_file = tmp_path / "group_chat.sqlite"
    store = GroupChatStore(db_path=db_file)

    room = store.get_or_create_conversation("conv_warden_team", title="Warden Team")

    # Step 1-3: Append initial events (seq 1..2)
    evt1, _ = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="matt",
        event_type="human_message",
        text="Initial message before disconnect",
    ))
    evt2, _ = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="warden",
        event_type="warden_message",
        text="Warden initial response",
    ))
    initial_seq = store.list_events("conv_warden_team")[-1].seq
    assert initial_seq == 2

    # Step 4-5: Client disconnects. Generate 3 real persisted events while client is offline (seq 3, 4, 5)
    evt3, _ = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="claude",
        event_type="agent_message",
        text="Claude background progress step 1 while client offline",
        metadata={"status": "working"},
    ))
    evt4, _ = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="spark",
        event_type="agent_message",
        text="Spark research completed while client offline",
        metadata={"status": "complete"},
    ))
    evt5, _ = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="codex",
        event_type="agent_message",
        text="Codex verification passed while client offline",
        metadata={"status": "complete"},
    ))

    # Step 6: Client reconnects using Last-Event-ID: 2
    replayed_events = store.list_events(conversation_id="conv_warden_team", since_seq=initial_seq)

    # Step 7: Prove exact replay counts & zero duplicates
    assert len(replayed_events) == 3
    assert [e.seq for e in replayed_events] == [3, 4, 5]
    assert replayed_events[0].id == evt3.id
    assert replayed_events[1].id == evt4.id
    assert replayed_events[2].id == evt5.id

    # Verify duplicate prevention: appending exact duplicate idempotency key produces no duplicate
    key = "idempotent_test_key_999"
    e_dup1, is_new1 = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="codex",
        text="Duplicate test message",
        idempotency_key=key,
    ))
    e_dup2, is_new2 = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="codex",
        text="Duplicate test message",
        idempotency_key=key,
    ))

    assert is_new1 is True
    assert is_new2 is False
    assert e_dup1.id == e_dup2.id
    assert e_dup1.seq == e_dup2.seq
