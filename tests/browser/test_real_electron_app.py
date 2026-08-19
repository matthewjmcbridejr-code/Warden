"""Real Electron E2E integration test running against packaged linux-unpacked binary."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

APP_BIN = "/home/matt/workspaces/warden/mcharness-public-export/desktop/dist-electron/linux-unpacked/warden-ai-desk"
SCREENSHOT_DIR = Path("/home/matt/workspaces/warden/mcharness-public-export/docs/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def get_main_page(context, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        for p in context.pages:
            url = p.url
            if ("index.html" in url or "app.asar" in url or (url.startswith("file:") and not url.endswith("about:blank"))) and "app.html" not in url:
                return p
        time.sleep(0.5)
    for p in context.pages:
        if "app.html" not in p.url:
            return p
    return context.pages[0]


def test_real_electron_app_lifecycle_and_team_chat():
    assert os.path.exists(APP_BIN), f"Packaged Electron app binary missing at {APP_BIN}"

    # --- Session 1: Launch Electron, Click Team Chat, Send Message, Switch Workspaces ---
    proc1 = subprocess.Popen([APP_BIN, "--no-sandbox", "--remote-debugging-port=9225"])
    time.sleep(3)

    try:
        with sync_playwright() as p:
            browser1 = p.chromium.connect_over_cdp("http://127.0.0.1:9225")
            context1 = browser1.contexts[0]
            page1 = get_main_page(context1)

            # Close onboarding dialog if modal
            page1.evaluate("() => { const d = document.getElementById('onboarding-dialog'); if (d) d.close(); }")
            page1.wait_for_timeout(2000)

            # 1. Ensure Team Chat workspace is active
            page1.wait_for_selector("button.workspace", timeout=10000)
            if page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace !== 'team-chat'"):
                page1.click("button[data-workspace='team-chat']", force=True)
            page1.set_viewport_size({"width": 1400, "height": 900})
            page1.wait_for_selector("#team-chat-workspace:not([hidden])", timeout=10000)

            # 2. Verify active workspace button
            active_workspace = page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace")
            assert active_workspace == "team-chat", f"Expected active workspace button to be team-chat, got {active_workspace}"

            # 3. Locate iframe and verify #chat-messages-stream
            frame_element = page1.wait_for_selector("#team-chat-frame")
            frame = frame_element.content_frame()
            assert frame is not None, "Failed to get iframe content frame"
            
            stream = frame.wait_for_selector("#chat-messages-stream", state="attached", timeout=10000)
            assert stream is not None

            # 4. Real user send interaction inside iframe
            textarea = frame.wait_for_selector("#chat-input-textarea", state="attached", timeout=10000)
            assert textarea is not None
            frame.fill("#chat-input-textarea", "Hello from Real Electron Integration Test!", force=True)
            frame.evaluate("() => document.getElementById('chat-send-btn')?.click()")

            # 5. Verify event text appears in stream
            stream_text = ""
            for _ in range(20):
                stream_text = frame.locator("#chat-messages-stream").text_content()
                if "Hello from Real Electron Integration Test!" in stream_text:
                    break
                page1.wait_for_timeout(500)
            assert "Hello from Real Electron Integration Test!" in stream_text
            assert frame.input_value("#chat-input-textarea") == ""

            # 6. Switch to Web Platforms workspace
            page1.click("button[data-workspace='chat']", force=True)
            page1.wait_for_timeout(500)
            assert page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace") == "chat"

            # 7. Switch back to Team Chat
            page1.click("button[data-workspace='team-chat']", force=True)
            page1.wait_for_timeout(500)
            assert page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace") == "team-chat"
            assert frame.wait_for_selector("#chat-messages-stream") is not None

            # 8. Capture Real Electron Window Screenshot
            electron_screenshot_path = SCREENSHOT_DIR / "real_electron_team_chat_window.png"
            page1.screenshot(path=str(electron_screenshot_path))
            print(f"\n[CAPTURED REAL ELECTRON WINDOW SCREENSHOT]: {electron_screenshot_path}")

    finally:
        proc1.terminate()
        proc1.wait(timeout=5)

    time.sleep(2)

    # --- Session 2: Relaunch Electron App & Verify Team Chat Persistence ---
    proc2 = subprocess.Popen([APP_BIN, "--no-sandbox", "--remote-debugging-port=9226"])
    time.sleep(3)

    try:
        with sync_playwright() as p:
            browser2 = p.chromium.connect_over_cdp("http://127.0.0.1:9226")
            context2 = browser2.contexts[0]
            page2 = get_main_page(context2)

            # Verify workspace survived close/relaunch and restored team-chat
            restored_workspace = page2.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace")
            assert restored_workspace == "team-chat", f"Expected team-chat on relaunch, got {restored_workspace}"

            frame_element2 = page2.wait_for_selector("#team-chat-frame")
            frame2 = frame_element2.content_frame()
            assert frame2 is not None
            assert frame2.wait_for_selector("#chat-messages-stream") is not None
            print("[PERSISTENCE PROOF PASSED]: Team Chat workspace survived app close & relaunch!")

    finally:
        proc2.terminate()
        proc2.wait(timeout=5)
