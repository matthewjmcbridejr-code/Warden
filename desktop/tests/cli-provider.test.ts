import { describe, expect, it } from 'vitest';
import { mapCliEvent } from '../src/main/cli-provider';

describe('structured CLI event normalization', () => {
  it('preserves Claude result metadata and normalizes completion', () => { const raw = { type: 'result', result: 'done', session_id: 'session-1', usage: { input_tokens: 2 } }; const event = mapCliEvent('claude', raw, 'run-1'); expect(event?.type).toBe('run.completed'); expect(event?.payload.finalMessage).toBe('done'); expect(event?.providerPayload).toBe(raw); });
  it('streams Grok text and captures its session end', () => { expect(mapCliEvent('grok', { type: 'text', data: 'hello' }, 'run-1')?.payload.delta).toBe('hello'); expect(mapCliEvent('grok', { type: 'end', sessionId: 'grok-session', stopReason: 'EndTurn' }, 'run-1')?.type).toBe('run.completed'); });
  it('normalizes Gemini tool and result records', () => { expect(mapCliEvent('gemini', { type: 'tool_use', tool_name: 'read_file', parameters: { path: 'README.md' } }, 'run-1')?.type).toBe('tool.started'); expect(mapCliEvent('gemini', { type: 'result', response: 'verified' }, 'run-1')?.payload.finalMessage).toBe('verified'); });
});
