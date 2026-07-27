import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(join(process.cwd(), 'src/renderer/simple-build.ts'), 'utf8');
const html = readFileSync(join(process.cwd(), 'src/renderer/index.html'), 'utf8');

describe('Simple Build product integration', () => {
  it('wires approval, cancellation, follow-up, and recovery controls', () => {
    for (const id of ['sb-approve-once', 'sb-deny', 'sb-approve-details', 'sb-cancel', 'sb-send-followup']) {
      expect(html).toContain(`id="${id}"`); expect(source).toContain(`$('#${id}').addEventListener`);
    }
    expect(source).toContain('window.wardenDesk.runs.approve');
    expect(source).toContain('window.wardenDesk.runs.cancel');
    expect(source).toContain('window.wardenDesk.runs.resume');
  });

  it('uses the durable project identity and restores its active run', () => {
    expect(source).toContain('projectId: project.id');
    expect(source).toContain('run.id === project.activeRunId');
    expect(source).toContain('window.wardenDesk.runs.list(project.id)');
    expect(source).toContain('activeRunId: run.id');
  });

  it('surfaces operation failures and routes unsafe projects to the real Developer Mode', () => {
    expect(html).toContain('role="alert"');
    expect(html).toContain('Inspect in Advanced mode');
    expect(source).toContain('showError(error)');
    expect(source).toContain('options.openDeveloperMode');
  });

  it('supports Warden 0.5 beginner mission templates and 1-click playground creation', () => {
    for (const id of ['sb-create-playground', 'provider-setup-button', 'handoff-to-build']) {
      expect(html).toContain(`id="${id}"`);
    }
    expect(source).toContain('MISSION_TEMPLATES');
    expect(source).toContain('data-template');
    expect(source).toContain('createPlayground');
  });
});
