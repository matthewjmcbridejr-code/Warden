import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { collectEvidence } from '../src/main/evidence';
import { RunStore } from '../src/main/run-store';

describe('run evidence', () => {
  it('captures untracked files, bounded content, and test commands', async () => {
    const cwd = mkdtempSync(join(tmpdir(), 'warden-evidence-project-')); execFileSync('git', ['init', '-q', cwd]); writeFileSync(join(cwd, 'new.js'), 'export const ok = true;\n');
    const store = new RunStore(mkdtempSync(join(tmpdir(), 'warden-evidence-store-'))); let run = store.create({ provider: 'codex', project: 'demo', cwd, prompt: 'test' });
    run.events.push({ type: 'command.completed', runId: run.id, provider: 'codex', timestamp: new Date().toISOString(), payload: { command: 'node --test', exitCode: 0, output: 'pass' } });
    const evidence = await collectEvidence(run); expect(evidence.changedFiles).toContain('new.js'); expect(evidence.diff).toContain('+++ b/new.js'); expect(evidence.tests[0].exitCode).toBe(0);
  });
});
