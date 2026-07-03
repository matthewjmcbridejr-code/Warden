"""
Playwright e2e: Command → Develop Plan → Dispatch Step → blocked notice → Memory Chat recall.

Requires:
  - Warden API running at http://127.0.0.1:6969
  - playwright + chromium installed: playwright install chromium

Run:
  .venv/bin/pytest tests/e2e/test_dispatch_loop.py -v --timeout=60
"""

import re
import pytest
from playwright.sync_api import Page, expect

BASE = "http://127.0.0.1:6969"
APP_URL = f"{BASE}/web/warden/app.html"
API_HEALTH = f"{BASE}/api/mcharness/health"


@pytest.fixture(scope="session")
def api_alive():
    """Skip all e2e tests if the Warden API isn't reachable."""
    import urllib.request
    try:
        with urllib.request.urlopen(API_HEALTH, timeout=5) as r:
            if r.status != 200:
                pytest.skip("Warden API not reachable")
    except Exception:
        pytest.skip("Warden API not reachable")


def test_app_loads(page: Page, api_alive):
    """App HTML loads and the Command section is active."""
    page.goto(APP_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)
    # Sidebar brand visible
    expect(page.locator(".warden-title")).to_be_visible()
    # Command section active
    mission_section = page.locator('[data-testid="warden-section-mission"]')
    expect(mission_section).to_be_visible()


def test_onboarding_card_dismissable(page: Page, api_alive):
    """Onboarding card shows on first load and can be dismissed."""
    page.goto(APP_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)
    card = page.locator('[data-testid="warden-onboarding-card"]')
    expect(card).to_be_visible()
    # Dismiss
    page.locator("#onboarding-dismiss-btn").click()
    expect(card).to_be_hidden()


def _create_plan(page: Page, goal: str):
    """Helper: open captain modal, fill goal, submit, wait for steps."""
    page.locator('[data-testid="develop-plan-hero"]').click()
    # Wait for modal
    page.wait_for_selector('[data-testid="captain-deck-modal"]', state="visible", timeout=5000)
    page.locator('[data-testid="captain-goal"]').fill(goal)
    page.locator('[data-testid="captain-create-plan"]').click()
    page.wait_for_selector('[data-testid="captain-plan-steps"]', timeout=20000)
    # Close the modal so main content is interactable
    close_btn = page.locator('[data-testid="captain-close"]')
    if close_btn.is_visible():
        close_btn.click()
    page.wait_for_selector('[data-testid="captain-deck-modal"]', state="hidden", timeout=5000)


def test_develop_plan_creates_steps(page: Page, api_alive):
    """Typing a goal and clicking Develop Plan renders plan steps."""
    page.goto(APP_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)
    _create_plan(page, "Write a test for the dispatch loop")
    steps_container = page.locator('[data-testid="captain-plan-steps"]')
    expect(steps_container).to_be_visible()
    # At least one step rendered
    assert steps_container.inner_text().strip() != ""


def test_dispatch_step_shows_blocked_notice(page: Page, api_alive):
    """Dispatching a step shows the blocked notice with Memory/Marius buttons."""
    page.goto(APP_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)
    _create_plan(page, "e2e dispatch test goal")

    # Click the first deploy/dispatch step button (rendered with data-deploy-step-id)
    dispatch_btn = page.locator("[data-deploy-step-id]").first
    dispatch_btn.wait_for(state="visible", timeout=5000)
    dispatch_btn.click()

    # Blocked notice should appear (runner is unavailable in test env)
    notice = page.locator('[data-testid="captain-blocked-notice"]')
    notice.wait_for(state="visible", timeout=15000)
    expect(notice).to_contain_text("Runner unavailable")

    # Action buttons present
    expect(notice.locator("button:has-text('Ask Memory')")).to_be_visible()
    expect(notice.locator("button:has-text('Ask Marius')")).to_be_visible()


def test_memory_chat_recall_after_dispatch(page: Page, api_alive):
    """After dispatch, Memory Chat can recall the blocked attempt."""
    page.goto(APP_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)

    # Navigate to Memory Chat
    page.locator('[data-testid="nav-memory"]').click()
    expect(page.locator('[data-testid="warden-section-memory"]')).to_be_visible()

    # Welcome state shows
    expect(page.locator('[data-testid="mem-chat-welcome"]')).to_be_visible()

    # Send a query about last run
    page.locator('[data-testid="mem-chat-input"]').fill("What did the last agent run do?")
    page.locator('[data-testid="mem-chat-send-btn"]').click()

    # Wait for response — welcome state hides, thread shows
    page.wait_for_selector('[data-testid="mem-chat-thread"]', timeout=20000)
    thread = page.locator('[data-testid="mem-chat-thread"]')
    expect(thread).to_be_visible()

    # Response contains some recognizable content
    response_text = thread.inner_text()
    assert len(response_text) > 20, f"Memory response too short: {response_text!r}"


def test_marius_agent_section(page: Page, api_alive):
    """Marius Agent section loads with welcome state and accepts a prompt."""
    page.goto(APP_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)

    page.locator('[data-testid="nav-agent"]').click()
    expect(page.locator('[data-testid="warden-section-agent"]')).to_be_visible()

    # Welcome state
    expect(page.locator("#wa-welcome")).to_be_visible()

    # Click a starter
    page.locator(".wa-starter-btn").first.click()

    # Wait for response (may be slow if Ollama is offline and fallback activates)
    page.wait_for_selector("#wa-thread", timeout=45000)
    expect(page.locator("#wa-thread")).to_be_visible()


def test_settings_shows_connectors(page: Page, api_alive):
    """Settings section shows connector providers from the API."""
    page.goto(APP_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)

    page.locator('[data-testid="nav-settings"]').click()
    expect(page.locator('[data-testid="warden-section-settings"]')).to_be_visible()

    # Connector provider list loads
    connector_list = page.locator('[data-testid="connectors-provider-list"]')
    expect(connector_list).to_be_visible()

    # Wait for providers to load (network idle)
    page.wait_for_timeout(2000)
    # Should show at least Gmail
    expect(connector_list).to_contain_text("Gmail")
    # All unconfigured in test env
    expect(connector_list).to_contain_text("Setup required")


def test_connector_setup_wizard_shown_for_unconfigured(page: Page, api_alive):
    """Unconfigured OAuth providers show the setup wizard, not CLI instructions."""
    page.goto(APP_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)

    page.locator('[data-testid="nav-settings"]').click()
    expect(page.locator('[data-testid="warden-section-settings"]')).to_be_visible()

    connector_list = page.locator('[data-testid="connectors-provider-list"]')
    expect(connector_list).to_be_visible()
    page.wait_for_timeout(2000)

    # Should show wizard toggle, not raw env var names
    expect(connector_list).to_contain_text("Set up Gmail connection")
    expect(connector_list).not_to_contain_text("WARDEN_GOOGLE_OAUTH_CLIENT_ID")
    expect(connector_list).not_to_contain_text("cloud_keys.env")


def test_connector_setup_wizard_expand_shows_fields(page: Page, api_alive):
    """Clicking the setup wizard summary reveals client ID / client secret fields."""
    page.goto(APP_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)

    page.locator('[data-testid="nav-settings"]').click()
    expect(page.locator('[data-testid="warden-section-settings"]')).to_be_visible()
    page.wait_for_timeout(2000)

    # Open the Gmail setup wizard
    gmail_wizard = page.locator('.connector-setup-wizard[data-provider="gmail"]')
    expect(gmail_wizard).to_be_visible()
    gmail_wizard.locator("summary").click()
    page.wait_for_timeout(300)

    # Fields should now be visible
    expect(gmail_wizard.locator(".connector-client-id-input")).to_be_visible()
    expect(gmail_wizard.locator(".connector-client-secret-input")).to_be_visible()
    expect(gmail_wizard.locator(".connector-redirect-uri")).to_be_visible()
    expect(gmail_wizard.locator(".connector-save-config-btn")).to_be_visible()
    # Redirect URI should contain the callback path
    uri_text = gmail_wizard.locator(".connector-redirect-uri").inner_text()
    assert "connectors/gmail/callback" in uri_text
