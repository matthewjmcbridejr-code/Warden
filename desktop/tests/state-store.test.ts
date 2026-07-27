import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StateStore } from '../src/main/state-store';
import { presetInput } from '../src/main/web-platforms';
import { discardSafeWorkspace, initializeGitRepository, isCleanGitProject, startSafeWorkspace } from '../src/main/git-safe-loop';

describe('project, profile, and platform persistence', () => {
  afterEach(() => vi.unstubAllEnvs());

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

  it('restores localhost platforms only in explicit development mode', () => {
    vi.stubEnv('NODE_ENV', 'development'); const root = mkdtempSync(join(tmpdir(), 'warden-localhost-platform-')); const first = new StateStore(root);
    const platform = first.createPlatform({ name: 'Local fixture', startUrl: 'http://127.0.0.1:8765/' });
    const recovered = new StateStore(root);
    expect(recovered.state.platforms.find((item) => item.id === platform.id)?.startUrl).toBe('http://127.0.0.1:8765/');
  });

  it('skips corrupted platform definitions while preserving valid definitions', () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-invalid-platform-')); const initial = new StateStore(root); initial.save(); const file = initial.file; const raw = JSON.parse(readFileSync(file, 'utf8')) as Record<string, unknown>; raw.platforms = [{ name: 'Unsafe', startUrl: 'javascript:alert(1)' }, initial.state.platforms[0]]; writeFileSync(file, JSON.stringify(raw)); const recovered = new StateStore(root);
    expect(recovered.state.platforms).toHaveLength(1); expect(recovered.state.platforms[0].name).toBe('Claude'); expect(recovered.warning).toContain('Skipped invalid platform');
  });

  it('creates sample playgrounds collision-free when folders already exist on disk', () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-playgrounds-'));
    const store = new StateStore(root);
    const p1 = store.preparePlayground(root);
    expect(p1.name).toBe('Playground 1');
    expect(existsSync(p1.cwd)).toBe(true);

    const p2 = store.preparePlayground(root);
    expect(p2.name).toBe('Playground 2');
    expect(existsSync(p2.cwd)).toBe(true);
    expect(p2.cwd).not.toBe(p1.cwd);
  });

  it('executes atomic playground creation creating baseline files, initializing git, resulting in clean: true and functional startSafeWorkspace', async () => {
    const root = mkdtempSync(join(tmpdir(), 'warden-playgrounds-e2e-'));
    const store = new StateStore(root);
    const { cwd, name, filesToCommit } = store.preparePlayground(root);

    expect(existsSync(join(cwd, 'README.md'))).toBe(true);
    expect(existsSync(join(cwd, 'WELCOME.md'))).toBe(true);
    expect(existsSync(join(cwd, '.gitignore'))).toBe(true);

    await initializeGitRepository(cwd, { filesToCommit });
    const project = store.createProject(cwd, name);

    expect(project.name).toBe('Playground 1');
    expect(store.state.projects).toHaveLength(1);

    const status = await isCleanGitProject(cwd);
    expect(status.isGit).toBe(true);
    expect(status.clean).toBe(true);

    const workspace = await startSafeWorkspace(cwd);
    expect(workspace.status).toBe('active');
    await discardSafeWorkspace(cwd, workspace);
  });
});
