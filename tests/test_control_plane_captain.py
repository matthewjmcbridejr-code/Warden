"""Integration tests for Control Plane Captain Desk endpoint and approval resolution."""
from __future__ import annotations

from fastapi.testclient import TestClient
from src.warden.app import create_app
from src.warden.action_model import WardenActionV1
from src.warden.decision_model import WardenDecisionV1
from src.warden.capability_grants import ControlPlaneStore

app = create_app()
client = TestClient(app)


def test_captain_desk_control_plane_and_approval_resolution(tmp_path):
    import src.warden.capability_grants
    src.warden.capability_grants.DEFAULT_CONTROL_PLANE_PATH = tmp_path / "control.json"

    store = ControlPlaneStore(store_path=tmp_path / "control.json")

    action = WardenActionV1.create("warden_cancel_task", risk_class="DESTRUCTIVE")
    decision = WardenDecisionV1(action_id=action.action_id, verdict="ASK")
    approval = store.create_approval(action, decision)

    # 1. GET /api/mcharness/captain/desk -> verify control_plane section & pending approval in needs_you
    resp = client.get("/api/mcharness/captain/desk")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert "control_plane" in data
    assert data["control_plane"]["pending_approval_count"] >= 1
    assert data["needs_you"]["empty"] is False

    # 2. POST /api/mcharness/captain/approvals/resolve -> approve request
    res_resp = client.post(
        "/api/mcharness/captain/approvals/resolve",
        json={"approval_id": approval.approval_id, "verdict": "approved", "resolver": "operator"},
    )
    assert res_resp.status_code == 200
    res_data = res_resp.json()
    assert res_data["ok"] is True
    assert res_data["approval"]["status"] == "approved"
    assert res_data["grant"]["grant_id"] is not None
