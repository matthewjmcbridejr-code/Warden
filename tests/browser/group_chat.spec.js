import { test, expect } from '@playwright.test';

test.describe('Warden Agentic Group Chat v1 Surface', () => {
  const BASE_URL = process.env.WARDEN_TEST_URL || 'http://127.0.0.1:6969/web/warden/app.html';

  test('desktop group chat interaction & team routing flow', async ({ page }) => {
    await page.goto(BASE_URL);

    // 1. Verify Team Chat section navigation and header
    await expect(page.locator('#warden-section-group-chat')).toBeVisible();
    await expect(page.locator('#chat-room-title')).toHaveText('Mission Control');

    // 2. Type human message to team
    const textarea = page.locator('#chat-input-textarea');
    await textarea.fill('Finish the settings screen and make sure we are not missing anything.');
    await page.click('#chat-send-btn');

    // 3. Verify event bubbles are displayed
    const stream = page.locator('#chat-messages-stream');
    await expect(stream).toContainText('Finish the settings screen');
    await expect(page.locator('#chat-send-btn')).toBeEnabled({ timeout: 45_000 });
    await expect(stream).not.toContainText('Claude has UX');
    await expect(stream).not.toContainText('Spark Research');
  });

  test('mention autocomplete popup UI', async ({ page }) => {
    await page.goto(BASE_URL);

    const textarea = page.locator('#chat-input-textarea');
    await textarea.fill('Hey @');
    
    // Autocomplete menu appears
    const menu = page.locator('#mention-autocomplete-menu');
    await expect(menu).toBeVisible();
    await expect(menu).toContainText('@Claude');
    await expect(menu).toContainText('@Codex');
  });

  test('mobile viewport 390x844 responsive rendering', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(BASE_URL);

    await expect(page.locator('#warden-section-group-chat')).toBeVisible();
    await expect(page.locator('#chat-messages-stream')).toBeVisible();
    await expect(page.locator('#chat-input-textarea')).toBeVisible();
  });
});
