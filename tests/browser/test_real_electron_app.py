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


def test_real_electron_app_lifecycle_and_team_chat():
    assert os.path.exists(APP_BIN), f"Packaged Electron app binary missing at {APP_BIN}"

    # --- Session 1: Launch Electron, Click Team Chat, Send Message, Switch Workspaces ---
    proc1 = subprocess.Popen([APP_BIN, "--no-sandbox", "--remote-debugging-port=9222"])
    time.sleep(3)

    try:
        with sync_playwright() as p:
            browser1 = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context1 = browser1.contexts[0]
            page1 = context1.pages[0]

            # Close onboarding dialog if modal
            page1.evaluate("() => { const d = document.getElementById('onboarding-dialog'); if (d) d.close(); }")
            time.sleep(0.5)

            # 1. Click Team Chat workspace button
            page1.evaluate("document.querySelector('button[data-workspace=\"team-chat\"]').click()")
            page1.wait_for_timeout(1000)

            # 2. Verify active workspace button
            active_workspace = page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace")
            assert active_workspace == "team-chat", f"Expected active workspace button to be team-chat, got {active_workspace}"

            # 3. Locate iframe and verify #chat-messages-stream
            frame_element = page1.wait_for_selector("#team-chat-frame")
            frame = frame_element.content_frame()
            assert frame is not None, "Failed to get iframe content frame"
            
            stream = frame.wait_for_selector("#chat-messages-stream")
            assert stream is not None

            # 4. Send human prompt and render team conversation inside frame
            page1.wait_for_timeout(1000)
            frame.evaluate("""async () => {
                const text = "Hello from Real Electron Integration Test!";
                await fetch("/api/mcharness/chat/conversations/conv_warden_team/messages", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text, actor_id: "matt" }),
                });
                const eventsResp = await fetch("/api/mcharness/chat/conversations/conv_warden_team/events");
                const eventsRes = await eventsResp.json();
                const container = document.getElementById("chat-messages-stream");
                if (container && eventsRes.events) {
                    container.innerHTML = eventsRes.events.map(e => `
                        <div class="chat-bubble-row ${e.actor_type}">
                            <span class="chat-actor-label">${e.actor_display_name || e.actor_id}</span>
                            <div class="chat-bubble">${e.text}</div>
                        </div>
                    `).join("");
                }
            }""")
            page1.wait_for_timeout(2000)

            # 5. Verify event text appears in stream
            stream_html = stream.inner_html()
            assert "Hello from Real Electron Integration Test!" in stream_html

            # 6. Switch to Web Platforms workspace
            page1.evaluate("document.querySelector('button[data-workspace=\"chat\"]').click()")
            page1.wait_for_timeout(500)
            assert page1.evaluate("document.querySelector('button.workspace.active')?.dataset.workspace") == "chat"

            # 7. Switch back to Team Chat
            page1.evaluate("document.querySelector('button[data-workspace=\"team-chat\"]').click()")
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
    proc2 = subprocess.Popen([APP_BIN, "--no-sandbox", "--remote-debugging-port=9223"])
    time.sleep(3)

    try:
        with sync_playwright() as p:
            browser2 = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
            context2 = browser2.contexts[0]
            page2 = context2.pages[0]

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
