"""Warden v2.3 — UI consolidation checks (canonical app.html, legacy banners, warden-up)."""

import os
from pathlib import Path

from fastapi.testclient import TestClient

from src.server.api import app

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "warden"


def test_app_html_has_runner_sessions_section():
    html = (WEB / "app.html").read_text()
    assert 'data-section="runners"' in html
    assert 'data-testid="warden-section-runners"' in html
    assert 'src="./runners.js"' in html


def test_legacy_pages_carry_canonical_banner():
    for name in ("index.html", "command-deck.html"):
        html = (WEB / name).read_text()
        assert 'data-testid="legacy-ui-banner"' in html, name
        assert 'href="./app.html"' in html, name


def test_warden_up_script_exists_and_is_executable():
    script = ROOT / "scripts" / "warden-up"
    assert script.exists()
    assert os.access(script, os.X_OK)
    body = script.read_text()
    assert "uvicorn src.warden.app:app" in body and "WARDEN_PORT" in body


def test_docs_point_to_canonical_ui():
    for doc in (ROOT / "README.md", ROOT / "docs" / "quickstart.md"):
        text = doc.read_text()
        # The canonical entry is now the root URL served by `warden up`;
        # docs must mention the CLI rather than a deep app.html path.
        assert "warden up" in text or "warden-up" in text, doc.name


def test_runner_sessions_endpoint_serves_the_new_panel():
    client = TestClient(app)
    resp = client.get("/api/mcharness/runner/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_runner_sessions" in data or "items" in data
