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
});
