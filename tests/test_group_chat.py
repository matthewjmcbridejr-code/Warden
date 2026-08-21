"""Unit tests for GroupChatStore, monotonic event sequencing, and idempotency."""
from __future__ import annotations

import asyncio
import pytest
from pathlib import Path
from src.warden.group_chat import GroupChatStore, ChatEvent, parse_mentions, map_agent_display_name


def test_parse_mentions_and_agent_names():
    text = "Hey @Claude and @Codex, please verify what @Spark found for @team!"
    mentions = parse_mentions(text)
    assert mentions == ["Claude", "Codex", "Spark", "team"]

    name, actor_type = map_agent_display_name("claude")
    assert name == "Claude UX"
    assert actor_type == "agent"

    name_matt, type_matt = map_agent_display_name("matt")
    assert name_matt == "Matt"
    assert type_matt == "human"


def test_group_chat_store_persistence_and_monotonic_seq(tmp_path):
    db_file = tmp_path / "group_chat.sqlite"
    store = GroupChatStore(db_path=db_file)

    room = store.get_or_create_conversation("conv_warden_team", title="Warden Team")
    assert room.conversation_id == "conv_warden_team"
    assert room.title == "Warden Team"

    # Append 3 events
    evt1, is_new1 = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="matt",
        event_type="human_message",
        text="Finish the settings screen @Claude",
    ))
    assert is_new1 is True
    assert evt1.seq == 1
    assert evt1.mentions == ["Claude"]
    assert evt1.actor_display_name == "Matt"

    evt2, is_new2 = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="warden",
        event_type="warden_message",
        text="I split this into three pieces. Claude has UX, Spark has research, Codex will verify.",
    ))
    assert is_new2 is True
    assert evt2.seq == 2
    assert evt2.actor_display_name == "Warden"

    evt3, is_new3 = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="claude",
        event_type="agent_message",
        text="Picked up Settings UX. Reviewing current implementation.",
    ))
    assert is_new3 is True
    assert evt3.seq == 3

    # Re-open store from same DB file -> verify persistence & ordering
    store2 = GroupChatStore(db_path=db_file)
    events = store2.list_events("conv_warden_team")
    assert len(events) == 3
    assert [e.seq for e in events] == [1, 2, 3]
    assert events[0].text == "Finish the settings screen @Claude"
    assert events[2].actor_display_name == "Claude UX"


def test_group_chat_idempotency_deduplication(tmp_path):
    db_file = tmp_path / "group_chat.sqlite"
    store = GroupChatStore(db_path=db_file)

    key = "idem_task_completion_123"
    evt1, is_new1 = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="codex",
        event_type="task_completed",
        text="Ran all implementation checks — passing ✓",
        idempotency_key=key,
    ))
    assert is_new1 is True

    # Appending exact duplicate event with same idempotency_key returns existing event!
    evt2, is_new2 = store.append_event(ChatEvent(
        conversation_id="conv_warden_team",
        actor_id="codex",
        event_type="task_completed",
        text="Ran all implementation checks — passing ✓",
        idempotency_key=key,
    ))
    assert is_new2 is False
    assert evt1.id == evt2.id
    assert evt1.seq == evt2.seq


def test_chat_event_ids_do_not_collide_within_same_millisecond():
    events = [ChatEvent(text=f"event {index}") for index in range(50)]
    assert len({event.id for event in events}) == len(events)


def test_store_instances_share_live_listener_for_same_database(tmp_path):
    db_file = tmp_path / "group_chat.sqlite"
    writer = GroupChatStore(db_path=db_file)
    subscriber = GroupChatStore(db_path=db_file)

    async def exercise_live_delivery():
        queue = subscriber.subscribe()
        try:
            event, _ = writer.append_event(ChatEvent(text="live browser update"))
            delivered = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert delivered.id == event.id
            assert delivered.seq == event.seq
        finally:
            subscriber.unsubscribe(queue)

    asyncio.run(exercise_live_delivery())


def test_agent_inbox_mentions(tmp_path):
    db_file = tmp_path / "group_chat.sqlite"
    store = GroupChatStore(db_path=db_file)

    store.append_event(ChatEvent(actor_id="matt", text="Hello @Claude, handle this task"))
    store.append_event(ChatEvent(actor_id="matt", text="Hello @Codex, check this"))

    claude_inbox = store.get_agent_inbox("claude")
    assert len(claude_inbox) == 1
    assert "Hello @Claude" in claude_inbox[0].text

    codex_inbox = store.get_agent_inbox("codex")
    assert len(codex_inbox) == 1
    assert "Hello @Codex" in codex_inbox[0].text


def test_process_human_message_routes_authoritative(tmp_path):
    db_file = tmp_path / "group_chat.sqlite"
    store = GroupChatStore(db_path=db_file)

    h_evt, responses = store.process_human_message("What can you help me with?")
    assert h_evt.actor_id == "matt"
    assert len(responses) >= 1
    assert responses[0].actor_id == "warden"
    assert responses[0].event_type == "warden_message"
    assert len(responses[0].text) > 10
