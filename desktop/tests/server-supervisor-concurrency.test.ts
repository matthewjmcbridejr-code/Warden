import { describe, expect, it, vi } from 'vitest';
import { ServerSupervisor } from '../src/main/server-supervisor';

describe('ServerSupervisor Concurrency & Cold Start', () => {
  it('deduplicates concurrent ensureRunning calls onto a single startup promise', async () => {
    const supervisor = new ServerSupervisor();
    let healthCallCount = 0;

    // Initially unhealthy, then becomes healthy
    vi.spyOn(supervisor, 'isHealthy').mockImplementation(async () => {
      healthCallCount++;
      return healthCallCount > 3;
    });

    // Mock internal start method
    const internalSpy = vi.spyOn(supervisor as any, '_startInternal').mockImplementation(async () => {
      await new Promise((r) => setTimeout(r, 50));
      return true;
    });

    // Fire 5 concurrent ensureRunning calls
    const [r1, r2, r3, r4, r5] = await Promise.all([
      supervisor.ensureRunning(),
      supervisor.ensureRunning(),
      supervisor.ensureRunning(),
      supervisor.ensureRunning(),
      supervisor.ensureRunning(),
    ]);

    expect(r1).toBe(true);
    expect(r2).toBe(true);
    expect(r3).toBe(true);
    expect(r4).toBe(true);
    expect(r5).toBe(true);

    // Verify _startInternal was called exactly once despite 5 concurrent callers
    expect(internalSpy).toHaveBeenCalledTimes(1);
  });

  it('exposes accurate startup status via getStatus', () => {
    const supervisor = new ServerSupervisor();
    const status = supervisor.getStatus();
    expect(status).toHaveProperty('healthy');
    expect(status).toHaveProperty('starting');
    expect(status).toHaveProperty('error');
    expect(status.starting).toBe(false);
  });
});
