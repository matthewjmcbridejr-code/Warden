"""Unit tests for Revisioned Context Delta Protocol."""
from __future__ import annotations

import json
from src.warden.context_protocol import (
    compute_context_revision,
    get_context_delta,
)


def test_context_revision_stability():
    memories = [
        {"memory_id": "m1", "kind": "decision", "title": "Use Python 3.12", "text": "Use Python 3.12", "project": "warden"},
        {"memory_id": "m2", "kind": "constraint", "title": "No Kafka", "text": "No Kafka", "project": "warden"},
    ]
    tasks = [
        {"task_id": "t1", "title": "Task Alpha", "status": "draft", "project": "warden"}
    ]

    rev1 = compute_context_revision(project="warden", tasks=tasks, memories=memories)

    # 1. Unrelated memory in another project must NOT change revision for 'warden'
    memories_unrelated = memories + [
        {"memory_id": "m3", "kind": "decision", "title": "Grademy UI", "text": "Grademy UI", "project": "grademy"}
    ]
    rev2 = compute_context_revision(project="warden", tasks=tasks, memories=memories_unrelated)
    assert rev1 == rev2, "Unrelated project memory must not alter context revision!"

    # 2. Timestamp or health check changes must NOT alter revision
    tasks_with_timestamp = [
        {"task_id": "t1", "title": "Task Alpha", "status": "draft", "project": "warden", "checked_at": "2026-08-16T12:00:00Z"}
    ]
    rev3 = compute_context_revision(project="warden", tasks=tasks_with_timestamp, memories=memories)
    assert rev1 == rev3, "Timestamps must not alter context revision!"

    # 3. Adding a relevant decision MUST change revision for 'warden'
    memories_relevant = memories + [
        {"memory_id": "m4", "kind": "decision", "title": "Use A2A Protocol", "text": "Use A2A Protocol", "project": "warden"}
    ]
    rev4 = compute_context_revision(project="warden", tasks=tasks, memories=memories_relevant)
    assert rev1 != rev4, "Relevant decision memory MUST alter context revision!"


def test_context_delta_no_change_payload_reduction():
    memories = [{"memory_id": "m1", "kind": "decision", "title": "Decision 1", "project": "warden"}]
    tasks = [{"task_id": "t1", "title": "Task 1", "status": "draft", "project": "warden"}]

    rev1 = compute_context_revision(project="warden", tasks=tasks, memories=memories)

    # No change delta
    delta_no_change = get_context_delta(since_revision=rev1, current_revision=rev1, project="warden", tasks=tasks, memories=memories)
    assert delta_no_change["changed"] is False
    assert delta_no_change["from_revision"] == rev1
    assert delta_no_change["to_revision"] == rev1

    no_change_bytes = len(json.dumps(delta_no_change).encode("utf-8"))

    # Single change delta
    memories2 = memories + [{"memory_id": "m2", "kind": "decision", "title": "Decision 2", "project": "warden"}]
    rev2 = compute_context_revision(project="warden", tasks=tasks, memories=memories2)

    delta_changed = get_context_delta(since_revision=rev1, current_revision=rev2, project="warden", tasks=tasks, memories=memories2)
    assert delta_changed["changed"] is True
    assert delta_changed["to_revision"] == rev2

    changed_bytes = len(json.dumps(delta_changed).encode("utf-8"))

    print(f"No-change delta bytes: {no_change_bytes}")
    print(f"Changed delta bytes:   {changed_bytes}")
    assert no_change_bytes < 100, "No-change delta payload must be tiny (<100 bytes)!"
