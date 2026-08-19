"""Automated Restart and Resume Verification Suite for Warden AI Desk 0.6.

Verifies that:
1. Finish jobs resume cleanly across process terminations.
2. Group chat conversations and rich cards survive restarts.
3. Brain memories and decisions persist on disk and reload on startup.
4. Active tasks can be reloaded and transitioned without data loss.
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import pytest

from src.warden.finish.models import FinishJob, FinishStage
from src.warden.finish.store import FinishJobStore
from src.warden.finish.pipeline import FinishPipeline
from src.warden.group_chat import GroupChatStore, ChatEvent


def test_finish_job_disk_persistence_and_resume():
    store1 = FinishJobStore()
    job_id = f"job_restart_test_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    job = FinishJob(
        job_id=job_id,
        project="AcmeRestartProject",
        repo_path="/tmp/acme",
        objective="Verify restart resilience",
    )
    job.record_transition(FinishStage.PLAN, "Planned steps")
    job.record_transition(FinishStage.BUILD, "Built assets")
    store1.save(job)

    # Re-instantiate store (simulating service restart)
    store2 = FinishJobStore()
    reloaded_job = store2.get(job_id)
    assert reloaded_job is not None
    assert reloaded_job.project == "AcmeRestartProject"
    assert reloaded_job.current_stage == FinishStage.BUILD
    assert len(reloaded_job.stage_history) >= 2

    # Advance pipeline on reloaded store
    pipeline = FinishPipeline(store=store2)
    next_job = pipeline.run_step(job_id)
    assert next_job.current_stage == FinishStage.PROVISION_AUTH

    # Re-instantiate a 3rd time to verify disk updates
    store3 = FinishJobStore()
    reloaded_job3 = store3.get(job_id)
    assert reloaded_job3 is not None
    assert reloaded_job3.current_stage == FinishStage.PROVISION_AUTH


def test_group_chat_events_persistence_and_reload():
    gc1 = GroupChatStore()
    conv_id = "conv_restart_verification"
    ev = ChatEvent(
        conversation_id=conv_id,
        actor_id="matt",
        actor_type="human",
        event_type="human_message",
        text="Can you preserve this message across restarts?",
    )
    saved_ev, _ = gc1.append_event(ev)

    # Re-instantiate GroupChatStore
    gc2 = GroupChatStore()
    events = gc2.list_events(conversation_id=conv_id)
    assert any(e.id == saved_ev.id and e.text == "Can you preserve this message across restarts?" for e in events)


def test_brain_decision_persistence_and_recall():
    gc = GroupChatStore()
    human_ev, resps = gc.process_human_message("Remember that I want Warden to be resilient across reboots.")
    assert any(r.event_type == "decision" for r in resps)

    # Recreate store and query recall
    gc_new = GroupChatStore()
    h_rec, recall_resps = gc_new.process_human_message("/recall resilient across reboots")
    assert any(r.event_type == "memory_recalled" for r in recall_resps)
