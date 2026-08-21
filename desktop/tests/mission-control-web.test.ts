import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const presentation = require('../../web/warden/mission-control.js') as {
  failureLabel: (value: string) => string;
  outcomeLabel: (value: string) => string;
  missionTitle: (value: string) => string;
  reduceEvents: (events: unknown[]) => any;
  recoverState: (state: any, sessions: unknown[], confirmations: unknown[]) => any;
};

function browserEvent(seq: number, phase: string, metadata: Record<string, unknown> = {}) {
  return {
    id: `event-${seq}`,
    seq,
    created_at: `2026-08-20T12:00:0${seq}.000Z`,
    event_type: phase === 'confirmation_required' ? 'approval_requested' : 'task_progress',
    approval_id: metadata.confirmation_id,
    metadata: { subsystem: 'computer_use', kind: 'browser', session_id: 'session-1', phase, ...metadata },
  };
}

describe('Mission Control browser presentation', () => {
  it('turns raw browser objectives into concise mission titles', () => {
    expect(presentation.missionTitle('navigate directly to http://127.0.0.1:8777/warden-confirmation-test.html and click the Delete account button once'))
      .toBe('Delete Account Confirmation Test');
    expect(presentation.missionTitle('find the Gemini Computer Use documentation'))
      .toBe('Find the Gemini Computer Use documentation');
  });

  it('reduces authentic runtime events into one evolving browser work item', () => {
    const state = presentation.reduceEvents([
      browserEvent(1, 'session_started', { objective: 'Find the Computer Use docs', provider: 'GeminiVertexComputerProvider', max_steps: 12 }),
      browserEvent(2, 'observation', { step: 1, title: 'Google', url: 'https://google.com/', screenshot_url: '/api/mcharness/computer/screenshots/step-1.png' }),
      browserEvent(3, 'action', { step: 2, summary: 'Open the documentation result' }),
    ]);
    const mission = state.missions['session-1'];
    expect(state.order).toEqual(['session-1']);
    expect(mission.title).toBe('Find the Computer Use docs');
    expect(mission.workItems).toHaveLength(1);
    expect(mission.provider).toBe('Gemini Computer Use');
    expect(mission.pageTitle).toBe('Google');
    expect(mission.currentAction).toBe('Open the documentation result');
    expect(mission.status).toBe('working');
    expect(mission.activity.length).toBeGreaterThan(0);
  });

  it('restores Needs You exactly once after replay and binds the pending action', () => {
    const requested = browserEvent(2, 'confirmation_required', {
      confirmation_id: 'confirmation-1', action_id: 'session-1_step_2', description: 'Submit this form', reason: 'This sends data externally', risk_level: 'high',
    });
    const state = presentation.reduceEvents([
      browserEvent(1, 'session_started', { objective: 'Submit the form' }),
      requested,
      requested,
    ]);
    const need = state.missions['session-1'].needsUser;
    expect(state.order).toEqual(['session-1']);
    expect(need.confirmationId).toBe('confirmation-1');
    expect(need.sessionId).toBe('session-1');
    expect(need.actionId).toBe('session-1_step_2');
    expect(state.missions['session-1'].status).toBe('needs_user');
  });

  it('distinguishes approval from execution and restores completion proof from snapshots', () => {
    let state = presentation.reduceEvents([
      browserEvent(1, 'session_started', { objective: 'Submit the form' }),
      browserEvent(2, 'confirmation_required', { confirmation_id: 'confirmation-1', action_id: 'session-1_step_2' }),
      browserEvent(3, 'confirmation_resolved', { confirmation_id: 'confirmation-1', action_id: 'session-1_step_2', decision: 'approve', executed: false }),
    ]);
    expect(state.missions['session-1'].status).toBe('working');
    expect(state.missions['session-1'].lastExecutedActionId).toBeUndefined();

    state = presentation.recoverState(state, [{
      session_id: 'session-1', objective: 'Submit the form', provider: 'GeminiVertexComputerProvider', status: 'completed', steps: 3,
      current_url: 'https://example.test/done', page_title: 'Complete', latest_screenshot: '/api/mcharness/computer/screenshots/final.png', result: 'Form submitted',
    }], []);
    expect(state.missions['session-1'].status).toBe('completed');
    expect(state.missions['session-1'].evidence[0].summary).toBe('Form submitted');
  });

  it('keeps provider payloads and coordinate chatter out of primary Mission copy', () => {
    const state = presentation.reduceEvents([
      browserEvent(1, 'session_started', { objective: 'Search the docs' }),
      browserEvent(2, 'action', { action_type: 'type', summary: "Typed 'private search' at (499, 399)" }),
    ]);
    expect(state.missions['session-1'].currentAction).toBe('Entering text in the page');
    expect(presentation.failureLabel("429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}"))
      .toBe('Gemini Computer Use reached its current service quota. Try again shortly.');
    expect(presentation.failureLabel('Reauthentication is needed. Run gcloud auth application-default login'))
      .toBe('Gemini Computer Use needs Google Cloud sign-in again before it can continue.');
    expect(presentation.outcomeLabel("Action prevented: Action 'Clicked at (640, 400)' was denied"))
      .toBe('Action prevented by operator. The browser action was not run.');
  });

  it('does not let stale REST recovery overwrite a newer terminal SSE event', () => {
    const state = presentation.reduceEvents([
      browserEvent(1, 'session_started', { objective: 'Controlled action' }),
      browserEvent(2, 'session_completed', { status: 'completed', steps: 2, result: 'Finished' }),
    ]);
    presentation.recoverState(state, [{
      session_id: 'session-1', objective: 'Controlled action', status: 'waiting_for_confirmation', steps: 2,
    }], [{ confirmation_id: 'stale', session_id: 'session-1', action_id: 'stale-action', action_type: 'click', description: 'Stale action', status: 'pending' }]);
    expect(state.missions['session-1'].status).toBe('completed');
    expect(state.missions['session-1'].needsUser).toBeNull();
  });
});
