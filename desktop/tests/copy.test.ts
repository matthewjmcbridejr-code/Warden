import { describe, expect, it } from 'vitest';
import { providerOnboardingCopy, recommendedProviderLine, translateApproval, translateEvent } from '../src/renderer/copy';
import type { NormalizedRunEvent, ProviderAuthReport } from '../src/shared/types';

const baseEvent = { runId: 'run-1', provider: 'codex', timestamp: new Date().toISOString() };

describe('translateEvent', () => {
  it('never leaks a raw shell command for a package install', () => {
    const event: NormalizedRunEvent = { ...baseEvent, type: 'command.started', payload: { command: 'npm install @radix-ui/react-dialog --save' } };
    const text = translateEvent(event);
    expect(text).not.toMatch(/npm|radix|--save/);
    expect(text).toBe('Adding a package your project needs');
  });

  it('renders a plain-language line for every known event type', () => {
    const types: NormalizedRunEvent['type'][] = ['run.started', 'command.started', 'command.completed', 'file.changed', 'tool.started', 'tool.completed', 'test.completed', 'approval.requested', 'run.completed', 'run.failed', 'run.cancelled'];
    for (const type of types) {
      const event: NormalizedRunEvent = { ...baseEvent, type, payload: {} };
      expect(translateEvent(event).length).toBeGreaterThan(0);
    }
  });

  it('falls back gracefully for an unrecognized event type', () => {
    const event = { ...baseEvent, type: 'something.new', payload: {} } as unknown as NormalizedRunEvent;
    expect(translateEvent(event)).toBe('Working on it');
  });
});

describe('translateApproval', () => {
  it('translates an npm install approval into consumer language, not the raw command', () => {
    const copy = translateApproval({ title: 'Approve command', detail: 'npm install @radix-ui/react-dialog --save' });
    expect(copy.title).toBe('Wants to add a package to this project');
    expect(copy.source).toBe('npm');
    expect(copy.title).not.toMatch(/npm|radix/);
  });

  it('translates a file deletion approval', () => {
    const copy = translateApproval({ title: 'Approve command', detail: 'rm -rf build/legacy' });
    expect(copy.title).toBe('Wants to delete one or more files');
  });

  it('falls back to the raw title when nothing matches', () => {
    const copy = translateApproval({ title: 'Approve something unusual', detail: 'some unmapped detail' });
    expect(copy.title).toBe('Approve something unusual');
  });
});

describe('providerOnboardingCopy', () => {
  it('recommends Codex only when subscription-authenticated', () => {
    const report: ProviderAuthReport = { provider: 'codex', state: 'subscription_authenticated', source: 'subscription', installed: true, client: 'codex app-server', detail: 'ok', canStart: true, apiFallbackAvailable: false, checkedAt: new Date().toISOString() };
    const copy = providerOnboardingCopy('codex', report);
    expect(copy.action).toBe('ready');
    expect(copy.headline).toBe(recommendedProviderLine('codex'));
  });

  it('asks to connect when disconnected, never assumes API billing', () => {
    const copy = providerOnboardingCopy('codex', undefined);
    expect(copy.action).toBe('connect');
    expect(copy.headline).toMatch(/Connect Codex/);
  });

  it('does not report ready for api_key_authenticated state', () => {
    const report: ProviderAuthReport = { provider: 'codex', state: 'api_key_authenticated', source: 'api_key', installed: true, client: 'codex app-server', detail: 'api key only', canStart: false, apiFallbackAvailable: true, checkedAt: new Date().toISOString() };
    const copy = providerOnboardingCopy('codex', report);
    expect(copy.action).not.toBe('ready');
  });
});
