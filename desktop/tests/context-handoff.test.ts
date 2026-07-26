import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';
import { assembleContext, formatContext } from '../src/main/context-assembler';
import { createHandoff } from '../src/main/handoff';
import { RunStore } from '../src/main/run-store';

describe('context and handoffs', () => {
  it('assembles bounded project context without unrelated memories', async () => {
    const cwd = mkdtempSync(join(tmpdir(), 'warden-project-')); execFileSync('git', ['init', '-q', cwd]); writeFileSync(join(cwd, 'AGENTS.md'), 'Run npm test.'); mkdirSync(join(cwd, 'skills', 'review'), { recursive: true });
    const pack = await assembleContext(cwd); expect(pack.instructionFiles[0].content).toContain('npm test'); expect(pack.skills).toContain('review'); expect(formatContext(pack)).toContain('<warden-context>');
  });
  it('creates a compact resumable handoff', () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-handoff-')); const store = new RunStore(root); const run = store.create({ provider: 'codex', project: 'demo', cwd: '/tmp', prompt: 'Fix it' }); run.status = 'completed'; run.evidence.changedFiles = ['src/a.ts']; run.evidence.finalMessage = 'Done'; expect(createHandoff(run)).toContain('src/a.ts'); expect(createHandoff(run)).toContain('Done');
  });
});
