from __future__ import annotations

import src.warden.api as api_mod


def test_command_deck_empty_state(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "_BOARD_ROOT", tmp_path / "board")

    data = api_mod.get_command_deck_state()

    assert data["ok"] is True
    assert data["tasks"] == []
    assert data["summary"]["queued"] == 0
    assert data["summary"]["proof_needed"] == 0


def test_command_deck_demo_seed_and_subresources(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "_BOARD_ROOT", tmp_path / "board")
    request = api_mod._DemoSeedRequest(
        title="Demo Mission",
        description="Seeded for portfolio proof",
        agent="codex",
        priority="medium",
    )

    seeded = api_mod.post_command_deck_demo_seed(request)

    task = seeded["task"]
    assert task["title"] == "Demo Mission"
    assert task["status"] == "queued"
    assert task["tags"] == ["demo"]

    state_data = api_mod.get_command_deck_state()
    assert state_data["summary"]["queued"] == 1
    assert state_data["tasks"][0]["task_id"] == task["task_id"]

    proofs = api_mod.get_command_deck_proofs()
    relay = api_mod.get_command_deck_relay()
    events = api_mod.get_command_deck_events()
    assert proofs["ok"] is True
    assert relay["ok"] is True
    assert events["ok"] is True


def test_command_deck_completed_task_without_proof_needs_proof(tmp_path, monkeypatch):
    board = tmp_path / "board"
    completed = board / "tasks" / "completed"
    completed.mkdir(parents=True)
    (completed / "task-no-proof.json").write_text(
        '{"task_id":"task-no-proof","title":"Done without evidence","status":"completed"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(api_mod, "_BOARD_ROOT", board)

    data = api_mod.get_command_deck_state()

    assert data["tasks"][0]["proof_gate"] == "proof_needed"
    assert data["summary"]["proof_needed"] == 1


def test_command_deck_task_with_proof_is_verified(tmp_path, monkeypatch):
    board = tmp_path / "board"
    completed = board / "tasks" / "completed"
    completed.mkdir(parents=True)
    (completed / "task-proof.json").write_text(
        '{"task_id":"task-proof","title":"Done with evidence","status":"completed","proof":{"summary":"tests passed"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(api_mod, "_BOARD_ROOT", board)

    data = api_mod.get_command_deck_state()

    assert data["tasks"][0]["proof_gate"] == "verified"
    assert data["summary"]["proof_needed"] == 0
