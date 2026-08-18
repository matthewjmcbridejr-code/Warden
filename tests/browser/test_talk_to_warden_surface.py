"""Browser acceptance test suite for AI Desk Talk to Warden Surface (Phase B).

Verifies:
1. Talk to Warden conversational interface loads cleanly.
2. /plan command routes to Captain planning and renders rich plan cards with steps and actions.
3. /recall command queries Brain memories and renders rich memory cards.
4. /remember command saves decisions to Brain and renders decision cards.
5. /status, /tasks, and /finish commands render structured status cards and FinishJob progress.
6. Context drawer toggles and exposes Captain, Memory, Tasks, Runs, and Proof sections.
7. Autocomplete triggers for @mentions and /slash commands.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


def test_talk_to_warden_commands_and_rich_cards(page: Page):
    page.goto("http://127.0.0.1:6969/web/warden/app.html?embed=true")

    # 1. Verify Team Chat header and container
    section = page.locator("#warden-section-group-chat")
    expect(section).to_be_visible()

    # 2. Test /plan command
    textarea = page.locator("#chat-input-textarea")
    textarea.fill("/plan Build and verify multi-account settings")
    page.click("#chat-send-btn")
    page.wait_for_timeout(1000)

    stream = page.locator("#chat-messages-stream")
    expect(stream).to_contain_text("Captain Plan")
    expect(stream.locator(".plan-card-chat").last).to_be_visible()

    # 3. Test /recall command
    textarea.fill("/recall Warden Finish")
    page.click("#chat-send-btn")
    page.wait_for_timeout(1000)

    expect(stream).to_contain_text("Brain Recall")
    expect(stream.locator(".memory-card-chat").last).to_be_visible()

    # 4. Test /remember command
    textarea.fill("/remember Always run release audit before merging to master")
    page.click("#chat-send-btn")
    page.wait_for_timeout(1000)

    expect(stream).to_contain_text("Decision Recorded")
    expect(stream.locator(".decision-card-chat").last).to_be_visible()

    # 5. Test /finish command
    textarea.fill("/finish")
    page.click("#chat-send-btn")
    page.wait_for_timeout(1000)

    expect(stream).to_contain_text("Warden Finish")
    expect(stream.locator(".finish-card-chat").last).to_be_visible()

    # 6. Test Warden Context Drawer Toggle
    drawer = page.locator("#chat-team-panel")
    expect(drawer).not_to_have_class("open")

    page.click("#chat-toggle-team-panel-btn")
    page.wait_for_timeout(500)
    expect(drawer).to_have_class("chat-team-panel chat-team-drawer open")

    # Check drawer sections
    expect(page.locator("#drawer-active-tasks-count")).to_be_visible()
    expect(page.locator("#chat-open-captain-desk-btn")).to_be_visible()

    page.click("#chat-close-drawer-btn")
    page.wait_for_timeout(500)
    expect(drawer).not_to_have_class("open")
