import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.warden.app import app as standalone_app
from src.warden.branding import PRODUCT_NAME
from src.server.api import app


ROOT = Path(__file__).resolve().parents[1]


def test_standalone_app_serves_health_and_web():
    client = TestClient(standalone_app)
    assert app is standalone_app

    health_response = client.get("/api/mcharness/health")
    assert health_response.status_code == 200
    health = health_response.json()
    assert health["ok"] is True
    assert health["service"] == "mcharness-control-plane"

    warden_response = client.get("/web/warden/index.html")
    assert warden_response.status_code == 200
    assert "Warden" in warden_response.text
    assert "local-first agent ops" in warden_response.text


def test_branding_and_readme_are_public():
    branding = json.loads((ROOT / "branding.json").read_text(encoding="utf-8"))
    assert branding["product_name"] == "Warden"
    assert branding["repo_name"] == "warden"
    assert branding["public_url"] == ""
    assert PRODUCT_NAME == "Warden"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Warden" in readme
    assert "warden up" in readme  # canonical quick-start CLI is documented
    assert standalone_app.state.branding["public_url"] == ""