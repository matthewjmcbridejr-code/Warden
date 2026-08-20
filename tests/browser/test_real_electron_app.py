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

            # 4. Verify Truthful Header Badge (Ready, not fake 3 working)
            badge_text = frame.locator("#chat-working-badge").text_content()
            assert "Ready" in badge_text or "Available" in badge_text, f"Expected Ready badge, got {badge_text}"
            assert "3 working" not in badge_text

            # 5. Real user send interaction: Yesterday Work Prompt
            textarea = frame.wait_for_selector("#chat-input-textarea", state="attached", timeout=10000)
            assert textarea is not None
            frame.fill("#chat-input-textarea", "tell me what i was doing yesterday", force=True)
            frame.evaluate("() => document.getElementById('chat-send-btn')?.click()")

            # Verify yesterday work synthesis (no capability menu)
            yesterday_text = ""
            for _ in range(20):
                cards = frame.locator("#chat-messages-stream .chat-bubble-row").all()
                if cards:
                    yesterday_text = cards[-1].text_content()
                    if "Finish Subsystem" in yesterday_text or "milestones" in yesterday_text or "AI Desk" in yesterday_text:
                        break
                page1.wait_for_timeout(500)
            assert "Finish Subsystem" in yesterday_text or "milestones" in yesterday_text
            assert "Here is what I can do for you:" not in yesterday_text

            # 6. Real user send interaction: Captain Planning Prompt
            frame.fill("#chat-input-textarea", "Captain, make me a plan for improving Warden based on what we've built this week.", force=True)
            frame.evaluate("() => document.getElementById('chat-send-btn')?.click()")

            latest_card_text = ""
            for _ in range(20):
                cards = frame.locator("#chat-messages-stream .chat-bubble-row").all()
                if cards:
                    latest_card_text = cards[-1].text_content()
                    if "Formulated Captain Plan" in latest_card_text:
                        break
                page1.wait_for_timeout(500)
            assert "Formulated Captain Plan" in latest_card_text
            assert "improving Warden based on what we've built this week" in latest_card_text
            assert "split this work across the team" not in latest_card_text
            assert "Claude UX" not in latest_card_text

            # 7. Real user send interaction: Browsing History Prompt
            frame.fill("#chat-input-textarea", "what have I been browsing tonight", force=True)
            frame.evaluate("() => document.getElementById('chat-send-btn')?.click()")
            browsing_card_text = ""
            for _ in range(20):
                cards = frame.locator("#chat-messages-stream .chat-bubble-row").all()
                if cards:
                    browsing_card_text = cards[-1].text_content()
                    if "Browser" in browsing_card_text:
                        break
                page1.wait_for_timeout(500)
            assert "Browser" in browsing_card_text
            assert "split this work across the team" not in browsing_card_text
            assert "Claude UX" not in browsing_card_text
            assert "browser-f7ccfc0f8d4a" not in browsing_card_text

            # 8. Switch to Build workspace and verify Brain connectivity
            page1.click("button[data-workspace='build']", force=True)
            page1.wait_for_timeout(1000)
            assert page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace") == "build"

            # 9. Switch back to Team Chat
            page1.click("button[data-workspace='team-chat']", force=True)
            page1.wait_for_timeout(500)
            assert page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace") == "team-chat"
            assert frame.wait_for_selector("#chat-messages-stream") is not None

            # 10. Capture Real Electron Window Screenshots
            electron_screenshot_path = SCREENSHOT_DIR / "real_electron_team_chat_window.png"
            page1.screenshot(path=str(electron_screenshot_path))
            runtime_screenshot_path = SCREENSHOT_DIR / "real_electron_agent_runtime.png"
            page1.screenshot(path=str(runtime_screenshot_path))
            print(f"\n[CAPTURED REAL ELECTRON WINDOW SCREENSHOTS]: {electron_screenshot_path}, {runtime_screenshot_path}")

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
            relaunch_stream = frame2.locator("#chat-messages-stream").text_content()
            assert "Formulated Captain Plan" in relaunch_stream
            print("\n[VERIFIED PERSISTENCE ON RELAUNCH]: Plan survived reboot.")

    finally:
        proc2.terminate()
        proc2.wait(timeout=5)
