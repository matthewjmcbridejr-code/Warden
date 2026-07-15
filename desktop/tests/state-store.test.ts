import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { StateStore } from '../src/main/state-store';
import { presetInput } from '../src/main/web-platforms';

describe('project, profile, and platform persistence', () => {
  it('persists the completed first-run state without changing the state schema', () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-onboarding-')); const first = new StateStore(root);
    expect(first.state.onboardingComplete).toBe(false);
    first.patch({ onboardingComplete: true });
    const recovered = new StateStore(root);
    expect(recovered.state.version).toBe(2); expect(recovered.state.onboardingComplete).toBe(true);
  });

  it('persists editable platforms, profile assignment, order, removal, restoration, and projects', () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-state-')); const first = new StateStore(root);
    const work = first.createProfile('Work');
    let platform = first.createPlatform({ ...presetInput('hyperagent'), browserProfileId: work.id, pinned: true, order: 9 });
    platform = first.updatePlatform(platform.id, { name: 'HyperAgent Daily', trustedAuthDomains: [...platform.trustedAuthDomains, 'login.example.com'], enabled: false, order: 1 });
    const project = first.createProject('/tmp/warden-example', 'Warden Example', work.id); first.updateProject(project.id, { selectedPlatformId: platform.id, splitPlatformId: 'platform-claude', executionMode: 'codex', workspace: 'build' });
    first.removePlatform(platform.id);
    expect(first.state.removedPlatforms.map((item) => item.id)).toContain(platform.id);
    const restored = first.restorePlatform(platform.id); first.activateProject(project.id);

    const recovered = new StateStore(root); const saved = recovered.state.platforms.find((item) => item.id === restored.id)!; const savedProject = recovered.state.projects.find((item) => item.id === project.id)!;
    expect(saved.name).toBe('HyperAgent Daily'); expect(saved.browserProfileId).toBe(work.id); expect(saved.enabled).toBe(false); expect(saved.trustedAuthDomains).toContain('login.example.com');
    expect(savedProject.cwd).toBe('/tmp/warden-example'); expect(savedProject.executionMode).toBe('codex'); expect(recovered.state.activeProjectId).toBe(project.id);
  });

  it('recovers from corrupt JSON without silently discarding the diagnostic copy', () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-corrupt-')); const file = join(root, 'desktop-state.json'); writeFileSync(file, '{bad json'); const store = new StateStore(root);
    expect(store.warning).toContain('corrupt'); expect(store.state.platforms.length).toBeGreaterThan(0);
    const backup = store.warning!.match(/saved to (.+)\.$/)?.[1]; expect(backup && existsSync(backup)).toBe(true);
  });

  it('skips corrupted platform definitions while preserving valid definitions', () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-invalid-platform-')); const initial = new StateStore(root); initial.save(); const file = initial.file; const raw = JSON.parse(readFileSync(file, 'utf8')) as Record<string, unknown>; raw.platforms = [{ name: 'Unsafe', startUrl: 'javascript:alert(1)' }, initial.state.platforms[0]]; writeFileSync(file, JSON.stringify(raw)); const recovered = new StateStore(root);
    expect(recovered.state.platforms).toHaveLength(1); expect(recovered.state.platforms[0].name).toBe('Claude'); expect(recovered.warning).toContain('Skipped invalid platform');
  });
});
