"""Warden v2.2 — unified project view tests."""

import shutil

import pytest
from fastapi.testclient import TestClient

from src.warden.projects import PROJECTS_ROOT
from src.warden.workbench import (
    STORE,
    WorkbenchMemoryCreateRequest,
    WorkbenchSkillCreateRequest,
)
from src.server.api import app

PROJECT_ID = "v2test-context-project"


@pytest.fixture(autouse=True)
def clean_state():
    def _wipe():
        proj = PROJECTS_ROOT / PROJECT_ID
        if proj.exists():
            shutil.rmtree(proj)
        skill = STORE.root / "skills" / "v2test-context-skill.json"
        if skill.exists():
            skill.unlink()
    _wipe()
    yield
    _wipe()


def test_project_context_aggregates_memories_skills_and_gates():
    client = TestClient(app)
    resp = client.post(
        "/api/mcharness/projects/",
        json={"name": "V2Test Context Project", "project_id": PROJECT_ID, "repo_path": "."},
    )
    assert resp.status_code == 201, resp.text

    STORE.create_memory(
        WorkbenchMemoryCreateRequest(
            scope=PROJECT_ID,
            summary="v2.2 context aggregation decision",
            source="test",
            kind="decision",
            project_id=PROJECT_ID,
        )
    )
    STORE.create_skill(
        WorkbenchSkillCreateRequest(
            skill_id="v2test-context-skill",
            title="Context Skill",
            description="Skill visible in the project view.",
            acceptance_checks=["context endpoint returns it"],
        )
    )

    resp = client.get(f"/api/mcharness/projects/{PROJECT_ID}/context")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["project"]["project_id"] == PROJECT_ID
    assert any("context aggregation decision" in m["summary"] for m in data["memories"])
    assert any(s["skill_id"] == "v2test-context-skill" for s in data["skills"])
    assert isinstance(data["runs"], list)
    assert isinstance(data["worktrees"], list)
    # Every pending gate must carry its run linkage so a human can act on it.
    for gate in data["pending_gates"]:
        assert gate["status"] == "open"
        assert gate["run_id"]


def test_project_context_unknown_project_404():
    client = TestClient(app)
    resp = client.get("/api/mcharness/projects/does-not-exist-v2test/context")
    assert resp.status_code == 404
