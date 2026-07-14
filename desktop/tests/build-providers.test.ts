import { describe, expect, it } from 'vitest';
import { CodexAppServerAdapter, DisconnectedBuildProvider } from '../src/main/build-providers';

describe('structured provider boundary', () => {
  it('reports disconnected providers honestly', async () => {
    const provider = new DisconnectedBuildProvider('claude', 'SDK adapter pending');
    expect(provider.capabilities().streaming).toBe(false);
    await expect(provider.startRun({ prompt: 'test', project: 'Warden', workingDirectory: '/tmp' })).rejects.toThrow('not connected');
  });
  it('keeps Codex on the App Server path', async () => {
    const provider = new CodexAppServerAdapter();
    await expect(provider.startRun({ prompt: 'test', project: 'Warden', workingDirectory: '/tmp' })).rejects.toThrow('App Server');
  });
});
