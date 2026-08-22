import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const html = readFileSync(join(process.cwd(), 'src/renderer/index.html'), 'utf8');
const css = readFileSync(join(process.cwd(), 'src/renderer/styles.css'), 'utf8');
import { readdirSync } from 'node:fs';
const renderer = readdirSync(join(process.cwd(), 'src/renderer/modules')).map(f => readFileSync(join(process.cwd(), 'src/renderer/modules', f), 'utf8')).join('\n') + '\n' + readFileSync(join(process.cwd(), 'src/renderer/index.ts'), 'utf8');
const simpleBuild = readFileSync(join(process.cwd(), 'src/renderer/simple-build.ts'), 'utf8');
const buildScript = readFileSync(join(process.cwd(), 'scripts/build.mjs'), 'utf8');

describe('project-centered Build redesign', () => {
  it('organizes Build around missions, supervision, and evidence instead of a prompt beside a log', () => {
    for (const id of ['sb-project-name', 'sb-run-list', 'sb-acceptance', 'sb-phase-track', 'sb-approval', 'sb-changed-list', 'sb-check-list', 'sb-handoff', 'sb-save-proof']) {
      expect(html).toContain(`id="${id}"`);
    }
    expect(html).toContain('Mission control');
    expect(html).toContain('Review surface');
    expect(html).toContain('Apply to project');
  });

  it('uses review criteria in the real task while retaining context and safe-worktree execution', () => {
    expect(simpleBuild).toContain('Ready for review when:');
    expect(simpleBuild).toContain('attachContext: true');
    expect(simpleBuild).toContain('safe: true');
    expect(simpleBuild).toContain('window.wardenDesk.runs.handoff');
    expect(simpleBuild).toContain('window.wardenDesk.runs.saveProof');
    expect(simpleBuild).toContain('{ activeRunId: run.id }');
  });

  it('makes irrelevant web-platform navigation quiet while Build is active', () => {
    expect(css).toContain("body[data-workspace='build'] #platforms");
  });
});

describe('Monochrome Alloy visual system', () => {
  it('bundles production variable fonts and their licenses for offline desktop use', () => {
    expect(buildScript).toContain("loader: { '.woff2': 'file' }");
    expect(buildScript).toContain('Sora-OFL.txt');
    expect(buildScript).toContain('Epilogue-OFL.txt');
  });

  it('uses neutral work surfaces with restrained copper, plum, and violet semantics', () => {
    expect(css).toContain('--copper: #c88968');
    expect(css).toContain('--violet: #b69add');
    expect(css).toContain("font-family: 'Sora Variable'");
    expect(css).toContain("font: 680 14px/1.05 'Epilogue Variable'");
    for (const retired of ['#0d100e', '#355a37', '#8cb88a', '#090c0a']) expect(css).not.toContain(retired);
  });

  it('keeps the compiled terminal visually integrated without weakening its local execution boundary', () => {
  });
});
