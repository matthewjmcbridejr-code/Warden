import { test, expect } from '@playwright.test';

const BASE_URL = process.env.WARDEN_TEST_URL || 'http://127.0.0.1:6969/web/warden/app.html';
const SESSION_ID = 'computer-e2e-session';
const ACTION_ID = `${SESSION_ID}_step_2`;
const CONFIRMATION_ID = 'confirmation-e2e';

function event(seq, phase, metadata = {}, eventType = 'task_progress') {
  return {
    id: `mission-event-${seq}`,
    seq,
    conversation_id: 'conv_warden_team',
    actor_type: 'warden',
    actor_id: 'warden',
    actor_display_name: 'Warden',
    event_type: eventType,
    text: `runtime ${phase}`,
    approval_id: metadata.confirmation_id || null,
    metadata: { kind: 'browser', subsystem: 'computer_use', session_id: SESSION_ID, phase, ...metadata },
    created_at: `2026-08-20T12:00:${String(seq - 100).padStart(2, '0')}.000Z`,
  };
}

test('Mission Control renders live Browser Work, exact approval binding, completion, and replay', async ({ page }) => {
  let pending = true;
  let status = 'waiting_for_confirmation';
  let result = null;
  let capturedDecision = null;
  const events = [
    event(101, 'session_started', { objective: 'Find the Gemini Computer Use documentation', provider: 'GeminiVertexComputerProvider', max_steps: 8 }, 'agent_working'),
    event(102, 'observation', { step: 1, title: 'Gemini Computer Use docs', url: 'https://cloud.google.com/vertex-ai/generative-ai/docs/computer-use', screenshot_url: '/api/mcharness/computer/screenshots/e2e.png' }, 'context_updated'),
    event(103, 'action', { step: 2, action_id: ACTION_ID, action_type: 'click', summary: 'Open the external documentation link' }),
    event(104, 'confirmation_required', { step: 2, confirmation_id: CONFIRMATION_ID, action_id: ACTION_ID, action_type: 'click', description: 'Open an external link', reason: 'This leaves the current site', risk_level: 'high', title: 'Gemini Computer Use docs', url: 'https://cloud.google.com/vertex-ai/generative-ai/docs/computer-use', screenshot_url: '/api/mcharness/computer/screenshots/e2e.png' }, 'approval_requested'),
  ];

  await page.addInitScript(() => {
    localStorage.clear();
    class TestEventSource {
      constructor(url) { this.url = url; window.__missionEventSource = this; setTimeout(() => this.onopen && this.onopen(), 0); }
      close() {}
      emit(payload) { if (this.onmessage) this.onmessage({ data: JSON.stringify(payload), lastEventId: String(payload.seq) }); }
    }
    window.EventSource = TestEventSource;
  });

  await page.route('**/api/mcharness/chat/conversations/conv_warden_team/events**', route => route.fulfill({ json: { ok: true, events } }));
  await page.route('**/api/mcharness/computer/sessions', route => route.fulfill({ json: {
    ok: true,
    sessions: [{
      session_id: SESSION_ID, objective: 'Find the Gemini Computer Use documentation', provider: 'GeminiVertexComputerProvider', status,
      steps: status === 'completed' ? 3 : 2, current_step: status === 'completed' ? 3 : 2, max_steps: 8,
      current_url: 'https://cloud.google.com/vertex-ai/generative-ai/docs/computer-use', page_title: 'Gemini Computer Use docs',
      latest_screenshot: '/api/mcharness/computer/screenshots/e2e.png', current_action_summary: 'Open the external documentation link', result,
    }],
  } }));
  await page.route('**/api/mcharness/computer/confirmations/pending', route => route.fulfill({ json: {
    ok: true,
    confirmations: pending ? [{ confirmation_id: CONFIRMATION_ID, session_id: SESSION_ID, action_id: ACTION_ID, action_type: 'click', description: 'Open an external link', status: 'pending' }] : [],
  } }));
  await page.route(`**/api/mcharness/computer/confirmations/${CONFIRMATION_ID}/resolve`, async route => {
    capturedDecision = route.request().postDataJSON();
    pending = false;
    status = capturedDecision.decision === 'approve' ? 'running' : 'completed';
    result = capturedDecision.decision === 'deny' ? 'Action prevented by operator' : null;
    await route.fulfill({ json: { ok: true, confirmation: { confirmation_id: CONFIRMATION_ID, status: capturedDecision.decision === 'approve' ? 'approved' : 'denied' } } });
  });
  await page.route('**/api/mcharness/computer/screenshots/e2e.png', route => route.fulfill({
    status: 200,
    contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
  }));

  await page.goto(BASE_URL);
  await expect(page.getByTestId('browser-work-card')).toBeVisible();
  await expect(page.getByTestId('mission-needs-you-card')).toContainText('Browser action paused');
  await expect(page.locator('#mission-current-status')).toHaveText('Needs You');
  await expect(page.locator('#chat-messages-stream')).not.toContainText('runtime confirmation_required');

  await page.getByRole('button', { name: 'Open Browser Work' }).click();
  await expect(page.getByTestId('browser-work-screenshot')).toBeVisible();
  await expect(page.locator('#browser-work-surface-body')).toContainText('Gemini Computer Use docs');
  await expect(page.locator('#browser-work-surface-body')).toContainText('cloud.google.com');

  await page.getByRole('button', { name: 'Approve' }).click();
  await expect.poll(() => capturedDecision).toEqual({
    decision: 'approve', operator_id: 'operator', expected_session_id: SESSION_ID, expected_action_id: ACTION_ID,
  });
  await expect(page.locator('#mission-current-status')).toHaveText('Working');

  const completedEvents = [
    event(105, 'action_executed', { step: 2, action_id: ACTION_ID, action_type: 'click', summary: 'Open the external documentation link', executed: true }),
    event(106, 'observation', { step: 2, title: 'Computer Use documentation', url: 'https://cloud.google.com/vertex-ai/generative-ai/docs/computer-use', screenshot_url: '/api/mcharness/computer/screenshots/e2e.png' }, 'context_updated'),
    event(107, 'session_completed', { status: 'completed', steps: 3, result: 'Documentation found', error: null }, 'task_completed'),
  ];
  for (const nextEvent of completedEvents) {
    events.push(nextEvent);
    await page.evaluate(payload => window.__missionEventSource.emit(payload), nextEvent);
  }
  status = 'completed';
  result = 'Documentation found';
  await expect(page.locator('#mission-current-status')).toHaveText('Done');
  await expect(page.getByTestId('browser-work-card')).toContainText('Documentation found');
  await expect(page.locator('#browser-work-surface-body')).toContainText('Completion evidence');

  await page.evaluate(payload => window.__missionEventSource.emit(payload), completedEvents[2]);
  await expect(page.getByTestId('browser-work-card')).toHaveCount(1);

  await page.reload();
  await expect(page.locator('#mission-current-status')).toHaveText('Done');
  await expect(page.getByTestId('browser-work-card')).toHaveCount(1);
  await expect(page.getByTestId('mission-needs-you-card')).toHaveCount(0);
});

test('Deny submits the exact bound action and clears Needs You', async ({ page }) => {
  let decisionBody = null;
  await page.addInitScript(() => {
    localStorage.clear();
    window.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 0); } close() {} };
  });
  const waitingEvent = event(201, 'confirmation_required', { confirmation_id: CONFIRMATION_ID, action_id: ACTION_ID, description: 'Delete this record', reason: 'Deletion cannot be undone' }, 'approval_requested');
  await page.route('**/api/mcharness/chat/conversations/conv_warden_team/events**', route => route.fulfill({ json: { ok: true, events: [event(200, 'session_started', { objective: 'Review the record' }), waitingEvent] } }));
  await page.route('**/api/mcharness/computer/sessions', route => route.fulfill({ json: { ok: true, sessions: [{ session_id: SESSION_ID, objective: 'Review the record', provider: 'GeminiVertexComputerProvider', status: decisionBody ? 'completed' : 'waiting_for_confirmation', steps: 1, result: decisionBody ? 'Action prevented by operator' : null }] } }));
  await page.route('**/api/mcharness/computer/confirmations/pending', route => route.fulfill({ json: { ok: true, confirmations: decisionBody ? [] : [{ confirmation_id: CONFIRMATION_ID, session_id: SESSION_ID, action_id: ACTION_ID, action_type: 'click', description: 'Delete this record', status: 'pending' }] } }));
  await page.route(`**/api/mcharness/computer/confirmations/${CONFIRMATION_ID}/resolve`, async route => {
    decisionBody = route.request().postDataJSON();
    await route.fulfill({ json: { ok: true, confirmation: { confirmation_id: CONFIRMATION_ID, status: 'denied' } } });
  });

  await page.goto(BASE_URL);
  await expect(page.getByTestId('mission-needs-you-card')).toBeVisible();
  await page.getByRole('button', { name: 'Deny' }).click();
  await expect.poll(() => decisionBody).toEqual({ decision: 'deny', operator_id: 'operator', expected_session_id: SESSION_ID, expected_action_id: ACTION_ID });
  await expect(page.getByTestId('mission-needs-you-card')).toHaveCount(0);
});
