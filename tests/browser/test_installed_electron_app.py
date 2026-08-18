"""E2E verification test running directly against the ACTUAL INSTALLED Warden AI Desk package (/opt/Warden AI Desk/warden-ai-desk)."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

INSTALLED_BIN = "/opt/Warden AI Desk/warden-ai-desk"
SCREENSHOT_DIR = Path("/home/matt/workspaces/warden/mcharness-public-export/docs/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def get_main_page(context, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        for p in context.pages:
            if "index.html" in p.url or "app.asar" in p.url or (p.url.startswith("file:") and not p.url.endswith("about:blank")):
                return p
        time.sleep(0.5)
    return context.pages[0]


def test_installed_electron_app_team_chat_and_persistence():
    assert os.path.exists(INSTALLED_BIN), f"Installed binary missing at {INSTALLED_BIN}"

    # --- Session 1: Launch Installed Electron Binary ---
    proc1 = subprocess.Popen([INSTALLED_BIN, "--no-sandbox", "--remote-debugging-port=9222"])
    time.sleep(3)

    try:
        with sync_playwright() as p:
            browser1 = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context1 = browser1.contexts[0]
            page1 = get_main_page(context1)

            # Close onboarding dialog if modal
            page1.evaluate("() => { const d = document.getElementById('onboarding-dialog'); if (d) d.close(); }")
            page1.wait_for_timeout(2000)

            # 1. Ensure Team Chat workspace is active
            page1.wait_for_selector("button.workspace", timeout=10000)
            if page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace !== 'team-chat'"):
                page1.click("button[data-workspace='team-chat']")
            page1.wait_for_selector("#team-chat-workspace:not([hidden])", timeout=10000)

            # 2. Verify active workspace button is team-chat
            active_workspace = page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace")
            assert active_workspace == "team-chat", f"Expected team-chat, got {active_workspace}"

            # 3. Locate iframe and verify #chat-messages-stream inside frame
            frame_element = page1.wait_for_selector("#team-chat-frame")
            frame = frame_element.content_frame()
            assert frame is not None, "Failed to get iframe content frame"

            stream = frame.wait_for_selector("#chat-messages-stream", state="visible", timeout=10000)
            assert stream is not None

            # 4. Test Team & Work Drawer Toggle using frame.click
            drawer = frame.wait_for_selector("#chat-team-panel")
            assert drawer is not None
            assert not frame.evaluate("document.getElementById('chat-team-panel').classList.contains('open')"), "Drawer should be closed by default"

            frame.click("#chat-toggle-team-panel-btn")
            page1.wait_for_timeout(500)
            assert frame.evaluate("document.getElementById('chat-team-panel').classList.contains('open')"), "Drawer should open after clicking Team & Work button"

            frame.click("#chat-close-drawer-btn")
            page1.wait_for_timeout(500)
            assert not frame.evaluate("document.getElementById('chat-team-panel').classList.contains('open')"), "Drawer should close after clicking close button"

            # 5. Post message via real UI interaction and verify stream content renders
            textarea = frame.wait_for_selector("#chat-input-textarea", state="visible", timeout=10000)
            assert textarea is not None
            frame.fill("#chat-input-textarea", "Installed real UI send verification")
            frame.click("#chat-send-btn")

            stream_text = ""
            for _ in range(20):
                stream_text = frame.locator("#chat-messages-stream").text_content()
                if "Installed real UI send verification" in stream_text:
                    break
                page1.wait_for_timeout(500)
            assert "Installed real UI send verification" in stream_text
            assert frame.input_value("#chat-input-textarea") == ""

            # 6. Test workspace switching: Team Chat -> Web Platforms (chat) -> Team Chat
            page1.click("button[data-workspace='chat']")
            page1.wait_for_timeout(500)
            assert page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace") == "chat"

            page1.click("button[data-workspace='team-chat']")
            page1.wait_for_timeout(500)
            assert page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace") == "team-chat"
            assert frame.wait_for_selector("#chat-messages-stream") is not None

            # 7. Test workspace switching: Team Chat -> Build -> Team Chat
            page1.click("button[data-workspace='build']")
            page1.wait_for_timeout(500)
            assert page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace") == "build"

            page1.click("button[data-workspace='team-chat']")
            page1.wait_for_timeout(500)
            assert page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace") == "team-chat"
            assert frame.wait_for_selector("#chat-messages-stream") is not None

            # 8. Capture Screenshot FROM THE REAL INSTALLED ELECTRON APP
            screenshot_path = SCREENSHOT_DIR / "installed_warden_ai_desk_team_chat.png"
            page1.screenshot(path=str(screenshot_path))
            print(f"\n[CAPTURED REAL INSTALLED ELECTRON WINDOW SCREENSHOT]: {screenshot_path}")

    finally:
        proc1.terminate()
        proc1.wait(timeout=5)

    time.sleep(2)

    # --- Session 2: Relaunch Installed Electron Binary & Verify Persistence ---
    proc2 = subprocess.Popen([INSTALLED_BIN, "--no-sandbox", "--remote-debugging-port=9223"])
    time.sleep(3)

    try:
        with sync_playwright() as p:
            browser2 = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
            context2 = browser2.contexts[0]
            page2 = get_main_page(context2)

            # Verify team-chat was restored automatically on relaunch
            restored_workspace = page2.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace")
            assert restored_workspace == "team-chat", f"Expected team-chat on relaunch, got {restored_workspace}"

            frame_element2 = page2.wait_for_selector("#team-chat-frame")
            frame2 = frame_element2.content_frame()
            assert frame2 is not None
            assert frame2.wait_for_selector("#chat-messages-stream") is not None
            print("[PERSISTENCE PROOF PASSED]: Installed app restored Team Chat across close & relaunch!")

    finally:
        proc2.terminate()
        proc2.wait(timeout=5)
