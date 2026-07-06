"""Warden v2.5 — bounded agent role tests."""

import pytest
from fastapi.testclient import TestClient

from src.warden.workbench import (
    STORE,
    ROLE_SAFETY_PROFILES,
    WorkbenchSkillCreateRequest,
    role_allows,
)
from src.server.api import app

ROLE_IDS = {"explorer", "planner", "builder", "verifier", "reviewer", "deployer", "archivist"}


@pytest.fixture(autouse=True)
def clean_skills():
    def _wipe():
        for name in ("deploy-skill-v2test", "edit-skill-v2test"):
            path = STORE.root / "skills" / f"{name}.json"
            if path.exists():
                path.unlink()
    _wipe()
    yield
    _wipe()


def test_role_profiles_are_registered():
    profiles = {p.profile_id for p in STORE.list_safety_profiles()}
    assert ROLE_IDS.issubset(profiles)
    assert "operator_local" in profiles


def test_role_allows_denies_forbidden_and_respects_allowlist():
    builder = next(p for p in ROLE_SAFETY_PROFILES if p.profile_id == "builder")
    assert role_allows(builder, "pytest -q") is True
    assert role_allows(builder, "git push --force") is False
    assert role_allows(builder, "curl network call") is False
    verifier = next(p for p in ROLE_SAFETY_PROFILES if p.profile_id == "verifier")
    assert role_allows(verifier, "run tests") is True
    assert role_allows(verifier, "rm file") is False  # outside allowlist


def test_builder_role_rejects_deploy_skill_dispatch():
    STORE.create_skill(WorkbenchSkillCreateRequest(
        skill_id="deploy-skill-v2test",
        title="Deploy",
        description="Restart the service.",
        commands_allowed=["deploy to production", "systemctl restart warden-api"],
    ))
    client = TestClient(app)
    resp = client.post(
        "/api/mcharness/skills/deploy-skill-v2test/dispatch",
        json={"repo_id": "mcharness-public-export", "objective": "ship it", "role": "builder"},
    )
    assert resp.status_code == 403
    assert "forbids" in resp.json()["detail"]


def test_explorer_role_cannot_dispatch_at_all():
    STORE.create_skill(WorkbenchSkillCreateRequest(
        skill_id="edit-skill-v2test",
        title="Edit",
        description="Edit some files.",
        commands_allowed=["edit files"],
    ))
    client = TestClient(app)
    resp = client.post(
        "/api/mcharness/skills/edit-skill-v2test/dispatch",
        json={"repo_id": "mcharness-public-export", "objective": "look around", "role": "explorer"},
    )
    assert resp.status_code == 403
    assert "read-only" in resp.json()["detail"]


def test_deployer_role_allows_deploy_skill():
    STORE.create_skill(WorkbenchSkillCreateRequest(
        skill_id="deploy-skill-v2test",
        title="Deploy",
        description="Restart the service.",
        commands_allowed=["deploy to production"],
    ))
    client = TestClient(app)
    resp = client.post(
        "/api/mcharness/skills/deploy-skill-v2test/dispatch",
        json={"repo_id": "mcharness-public-export", "objective": "restart after proof", "role": "deployer"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True and data["blocked"] is True  # runner off in tests
    assert data["gate_id"]


def test_unknown_role_404():
    client = TestClient(app)
    resp = client.post(
        "/api/mcharness/skills/whatever/dispatch",
        json={"repo_id": "x", "objective": "x", "role": "wizard"},
    )
    assert resp.status_code == 404
