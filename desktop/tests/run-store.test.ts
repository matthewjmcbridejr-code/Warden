import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { RunStore } from '../src/main/run-store';

describe('durable run store', () => {
  it('persists redacted runs, events, approvals, and proof', () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-runs-')); const first = new RunStore(root);
    const run = first.create({ provider: 'codex', project: 'demo', cwd: '/tmp', prompt: 'token=super-secret-value' });
    expect(run.prompt).toContain('[REDACTED]');
    first.appendEvent(run.id, { type: 'run.started', runId: run.id, provider: 'codex', timestamp: new Date().toISOString(), payload: { ok: true }, providerPayload: { token: 'another-secret-value' } });
    first.setProof(run.id, { local: 'saved', brain: 'unavailable' });
    const recovered = new RunStore(root).get(run.id)!;
    expect(recovered.events).toHaveLength(1); expect(JSON.stringify(recovered.events[0].providerPayload)).toContain('[REDACTED]'); expect(recovered.proof.local).toBe('saved');
  });
  it('persists safe-workspace acceptance and undo evidence across restart', () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-runs-')); const first = new RunStore(root);
    const run = first.create({ provider: 'codex', project: 'demo', projectId: 'project-demo', cwd: '/tmp/safe', projectCwd: '/tmp/demo', prompt: 'Fix it', safeWorkspace: { worktreePath: '/tmp/safe', branch: 'warden/task-demo', baseCommit: 'base', status: 'kept', consolidatedCommit: 'kept-commit' } });
    first.update(run.id, { safeWorkspace: { ...run.safeWorkspace!, status: 'undone', undoCommit: 'revert-commit' } });
    const recovered = new RunStore(root).get(run.id)!;
    expect(recovered.projectId).toBe('project-demo'); expect(recovered.safeWorkspace?.status).toBe('undone'); expect(recovered.safeWorkspace?.undoCommit).toBe('revert-commit');
  });
});
