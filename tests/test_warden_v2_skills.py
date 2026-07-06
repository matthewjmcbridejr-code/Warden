"""Warden v2.1 — skill playbook engine tests.

Covers: playbook-field CRUD, pre-v2 skill JSON loading unchanged (in-place
migration via model defaults), and skill dispatch creating a run with an open
proof gate and acceptance checks recorded as verifier evidence.
"""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from src.warden.workbench import (
    STORE,
    WorkbenchSkillCreateRequest,
)
from src.server.api import app


PLAYBOOK = dict(
    skill_id="ship-pr-v2test",
    title="Ship PR",
    description="Take a scoped change from branch to reviewed PR.",
    when_to_use="A bounded change is implemented and needs a PR with proof.",
    inspect_files=["README.md", "src/warden/api.py"],
    commands_allowed=["pytest -q", "git diff"],
    commands_forbidden=["git push --force", "rm -rf"],
    proof_format="branch, commit hash, files changed, test output",
    acceptance_checks=["pytest -q passes", "diff reviewed"],
    rollback_notes="git checkout master; delete branch",
    report_template="## Result\n{summary}",
)


@pytest.fixture(autouse=True)
def clean_skills():
    def _wipe():
        for name in ("ship-pr-v2test", "legacy-v2test"):
            path = STORE.root / "skills" / f"{name}.json"
            if path.exists():
                path.unlink()
        threads_dir = STORE.root / "threads"
        if threads_dir.exists():
            for p in threads_dir.glob("skill-dispatch-ship-pr*.json"):
                p.unlink()
    _wipe()
    yield
    _wipe()


def test_skill_create_persists_playbook_fields():
    skill = STORE.create_skill(WorkbenchSkillCreateRequest(**PLAYBOOK))
    assert skill.acceptance_checks == ["pytest -q passes", "diff reviewed"]
    assert skill.commands_forbidden == ["git push --force", "rm -rf"]
    loaded = STORE.get_skill("ship-pr-v2test")
    assert loaded.when_to_use == PLAYBOOK["when_to_use"]
    assert loaded.inspect_files == PLAYBOOK["inspect_files"]
    assert loaded.proof_format == PLAYBOOK["proof_format"]
    assert loaded.rollback_notes == PLAYBOOK["rollback_notes"]
    assert loaded.report_template == PLAYBOOK["report_template"]


def test_pre_v2_skill_json_loads_with_playbook_defaults():
    # A skill written before v2.1 has none of the playbook keys on disk.
    legacy = {
        "skill_id": "legacy-v2test",
        "title": "Legacy",
        "description": "Written before playbook fields existed.",
        "enabled": True,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    STORE.ensure_layout()
    (STORE.root / "skills" / "legacy-v2test.json").write_text(json.dumps(legacy))
    loaded = STORE.get_skill("legacy-v2test")
    assert loaded.acceptance_checks == []
    assert loaded.inspect_files == []
    assert loaded.when_to_use is None
    assert any(s.skill_id == "legacy-v2test" for s in STORE.list_skills())


def test_skill_crud_routes_roundtrip_playbook_fields():
    client = TestClient(app)
    resp = client.post("/api/mcharness/skills", json=PLAYBOOK)
    assert resp.status_code == 200, resp.text
    resp = client.get("/api/mcharness/skills/ship-pr-v2test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["acceptance_checks"] == PLAYBOOK["acceptance_checks"]
    assert data["commands_allowed"] == PLAYBOOK["commands_allowed"]


def test_skill_dispatch_creates_run_gate_and_acceptance_evidence():
    STORE.create_skill(WorkbenchSkillCreateRequest(**PLAYBOOK))
    client = TestClient(app)
    resp = client.post(
        "/api/mcharness/skills/ship-pr-v2test/dispatch",
        json={"repo_id": "mcharness-public-export", "objective": "Ship the v2 test change"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    # Public/test mode has no private runner: dispatch must record an honest block,
    # never a fake success.
    assert data["blocked"] is True
    run_id = data["run_id"]
    gate_id = data["gate_id"]

    run = STORE.get_run(run_id)
    gates = [g for g in run.proof_gates if g.gate_id == gate_id]
    assert gates and gates[0].status == "open" and gates[0].requires_human is True
    evidence = STORE.list_run_evidence(run_id)
    verifier = [e for e in evidence if e.source_type == "verifier"]
    assert verifier and "pytest -q passes" in verifier[0].summary
    assert verifier[0].verdict == "unknown"
    # Open gate blocks the run from reading as complete.
    assert any(e.event_type == "blocked" for e in run.events)


def test_skill_dispatch_disabled_skill_is_rejected():
    payload = dict(PLAYBOOK, enabled=False)
    STORE.create_skill(WorkbenchSkillCreateRequest(**payload))
    client = TestClient(app)
    resp = client.post(
        "/api/mcharness/skills/ship-pr-v2test/dispatch",
        json={"repo_id": "mcharness-public-export", "objective": "Should not run"},
    )
    assert resp.status_code == 409


def test_skill_dispatch_unknown_skill_404():
    client = TestClient(app)
    resp = client.post(
        "/api/mcharness/skills/does-not-exist-v2test/dispatch",
        json={"repo_id": "mcharness-public-export", "objective": "x"},
    )
    assert resp.status_code == 404
