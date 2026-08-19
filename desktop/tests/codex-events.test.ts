import { describe, expect, it } from 'vitest';
import { mapCodexNotification } from '../src/main/codex-adapter';

describe('Codex event normalization', () => {
  it('normalizes commands while preserving raw payload', () => {
    const raw = { threadId: 't', turnId: 'u', item: { type: 'commandExecution', id: 'i', command: 'npm test', cwd: '/tmp', exitCode: 0, aggregatedOutput: 'pass', status: 'completed' } };
    const event = mapCodexNotification('item/completed', raw, 'run-1')!;
    expect(event.type).toBe('command.completed'); expect(event.payload.exitCode).toBe(0); expect(event.providerPayload).toBe(raw);
  });
  it('normalizes completed turns and final messages', () => {
    const event = mapCodexNotification('turn/completed', { threadId: 't', turn: { id: 'u', status: 'completed', items: [{ type: 'agentMessage', text: 'finished' }] } }, 'run-1')!;
    expect(event.type).toBe('run.completed'); expect(event.payload.finalMessage).toBe('finished');
  });
  it('extracts structured error messages and avoids [object Object]', () => {
    const event = mapCodexNotification('turn/completed', {
      threadId: 't',
      turn: {
        id: 'u',
        status: 'failed',
        error: { message: 'Rate limit exceeded on model endpoint', code: 'rate_limit' }
      }
    }, 'run-1')!;
    expect(event.type).toBe('run.failed');
    expect(event.payload.error).toBe('Rate limit exceeded on model endpoint');
    expect(String(event.payload.error)).not.toContain('[object Object]');
  });
  it('extracts nested error object correctly', () => {
    const event = mapCodexNotification('error', {
      error: { error: { message: 'Failed to initialize workspace' } }
    }, 'run-1')!;
    expect(event.type).toBe('run.failed');
    expect(event.payload.error).toBe('Failed to initialize workspace');
  });
});
