"""Visual capture and verification script for Warden AI Desk Team Chat UI."""
from __future__ import annotations

import os
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path("/home/matt/workspaces/warden/mcharness-public-export/docs/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def test_capture_desktop_visual_proof():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        # 1. Desktop Window 1440x900 - Team Chat Embedded Presentation Mode
        page1 = browser.new_page(viewport={"width": 1440, "height": 900})
        page1.goto("http://127.0.0.1:6969/web/warden/app.html?embed=true")
        page1.wait_for_selector("#chat-messages-stream")
        page1.screenshot(path=str(SCREENSHOT_DIR / "01_team_chat_desktop_embedded_1440x900.png"))

        # Type human prompt and send
        page1.fill("#chat-input-textarea", "Finish the settings screen and make sure we are not missing anything.")
        page1.click("#chat-send-btn")
        page1.wait_for_timeout(1000)
        page1.screenshot(path=str(SCREENSHOT_DIR / "02_team_chat_active_conversation_1440x900.png"))

        # 2. Compact Desktop 1280x800
        page2 = browser.new_page(viewport={"width": 1280, "height": 800})
        page2.goto("http://127.0.0.1:6969/web/warden/app.html?embed=true")
        page2.wait_for_selector("#chat-messages-stream")
        page2.screenshot(path=str(SCREENSHOT_DIR / "03_team_chat_compact_1280x800.png"))

        # 3. Mobile Viewport 390x844
        page3 = browser.new_page(viewport={"width": 390, "height": 844})
        page3.goto("http://127.0.0.1:6969/web/warden/app.html?embed=true")
        page3.wait_for_selector("#chat-messages-stream")
        page3.screenshot(path=str(SCREENSHOT_DIR / "04_team_chat_mobile_390x844.png"))

        # 4. Captain Desk View
        page4 = browser.new_page(viewport={"width": 1440, "height": 900})
        page4.goto("http://127.0.0.1:6969/web/warden/app.html#captain-desk")
        page4.wait_for_timeout(1000)
        page4.screenshot(path=str(SCREENSHOT_DIR / "05_captain_desk_1440x900.png"))

        browser.close()
        print("Screenshots captured successfully in docs/screenshots/")
