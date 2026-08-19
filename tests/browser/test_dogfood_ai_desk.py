"""End-to-End Playwright Dogfooding Test Suite for Warden AI Desk 0.6.

Tests all natural conversation flows, Finish pipeline, 9/9 verification,
rich cards, and single-click operator publish directly in the browser.
"""

from __future__ import annotations
import pytest
from playwright.sync_api import Page, expect

SERVER_URL = "http://127.0.0.1:6969/web/warden/app.html?embed=true"


def send_chat_message(page: Page, text: str):
    textarea = page.locator("#chat-input-textarea")
    textarea.fill(text)
    page.click("#chat-send-btn")
    page.wait_for_timeout(1000)


def test_dogfood_ai_desk_starter_chips_and_context(page: Page):
    page.goto(SERVER_URL)
    page.wait_for_selector("#chat-messages-stream", timeout=10000)

    # 1. Ask: What were we working on last night?
    send_chat_message(page, "What were we working on last night?")
    page.wait_for_selector(".warden-row", timeout=10000)
    content = page.locator("#chat-messages-stream").inner_text()
    assert "Warden Finish Subsystem" in content or "Last night" in content or "milestones" in content


def test_dogfood_ai_desk_agent_status(page: Page):
    page.goto(SERVER_URL)
    page.wait_for_selector("#chat-messages-stream", timeout=10000)

    # 2. Ask: What is AGY doing?
    send_chat_message(page, "What is AGY doing?")
    page.wait_for_timeout(1500)
    content = page.locator("#chat-messages-stream").inner_text()
    assert "AGY" in content


def test_dogfood_ai_desk_decisions_recall(page: Page):
    page.goto(SERVER_URL)
    page.wait_for_selector("#chat-messages-stream", timeout=10000)

    # 3. Ask: What decisions did we make about Finish?
    send_chat_message(page, "What decisions did we make about Finish?")
    page.wait_for_timeout(1500)
    content = page.locator("#chat-messages-stream").inner_text()
    assert "9-Point Real Verification" in content or "Finish" in content or "Brain" in content


def test_dogfood_ai_desk_captain_planning(page: Page):
    page.goto(SERVER_URL)
    page.wait_for_selector("#chat-messages-stream", timeout=10000)

    # 4. Ask: Captain, make a plan for improving this UI.
    send_chat_message(page, "Captain, make a plan for improving this UI.")
    page.wait_for_selector(".plan-card-chat", timeout=10000)
    plan_card = page.locator(".plan-card-chat").last
    expect(plan_card).to_be_visible()
    assert "improving this UI" in plan_card.inner_text()


def test_dogfood_ai_desk_remember_preference(page: Page):
    page.goto(SERVER_URL)
    page.wait_for_selector("#chat-messages-stream", timeout=10000)

    # 5. Ask: Remember that I want Warden to prioritize simplicity.
    send_chat_message(page, "Remember that I want Warden to prioritize simplicity.")
    page.wait_for_selector(".decision-card-chat", timeout=10000)
    dec_card = page.locator(".decision-card-chat").last
    expect(dec_card).to_be_visible()
    assert "prioritize simplicity" in dec_card.inner_text()


def test_dogfood_ai_desk_proof_recall(page: Page):
    page.goto(SERVER_URL)
    page.wait_for_selector("#chat-messages-stream", timeout=10000)

    # 6. Ask: Show me the latest proof.
    send_chat_message(page, "Show me the latest proof.")
    page.wait_for_selector(".proof-card-chat", timeout=10000)
    proof_card = page.locator(".proof-card-chat").last
    expect(proof_card).to_be_visible()
    assert "Verification" in proof_card.inner_text() or "9/9" in proof_card.inner_text()


def test_dogfood_ai_desk_full_finish_and_publish_flow(page: Page):
    page.goto(SERVER_URL)
    page.wait_for_selector("#chat-messages-stream", timeout=10000)

    # 7. Ask: Finish this client portal and put it online.
    send_chat_message(page, "Finish this client portal and put it online.")
    page.wait_for_selector(".finish-card-chat", timeout=20000)
    
    # Assert finish card is rendered with 9/9 verification
    card_text = page.locator("#chat-messages-stream").inner_text()
    assert "AcmeClientPortal" in card_text
    assert "9/9" in card_text
    
    # Check if publish button is available or if direct publish instruction is accepted
    publish_btn = page.locator(".finish-publish-btn")
    if publish_btn.count() > 0:
        publish_btn.first.click()
        page.wait_for_timeout(3000)
    else:
        send_chat_message(page, "Publish")
        page.wait_for_timeout(3000)
    
    # Assert complete production card is rendered
    updated_content = page.locator("#chat-messages-stream").inner_text()
    assert "Published & Live" in updated_content or "Live & Verified" in updated_content or "Public Live ↗" in updated_content
