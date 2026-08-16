"""Browser E2E test for Agentic Group Chat v1 using Python Playwright."""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect
from fastapi.testclient import TestClient
from src.warden.app import create_app


def test_group_chat_ui_browser_e2e(page: Page):
    # Navigate to app UI
    page.goto("http://127.0.0.1:6969/web/warden/app.html")
    
    # 1. Verify section is visible
    section = page.locator("#warden-section-group-chat")
    expect(section).to_be_visible()

    # 2. Verify title
    title = page.locator("#chat-room-title")
    expect(title).to_have_text("Warden Team")

    # 3. Type human prompt
    textarea = page.locator("#chat-input-textarea")
    textarea.fill("Finish the settings screen and make sure we are not missing anything.")
    page.click("#chat-send-btn")

    # 4. Stream output verification
    stream = page.locator("#chat-messages-stream")
    expect(stream).to_contain_text("Finish the settings screen")
