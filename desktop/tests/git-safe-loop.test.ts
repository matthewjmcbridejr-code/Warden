import { execFile } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { discardSafeWorkspace, GitSafeLoopError, isCleanGitProject, keepSafeWorkspace, startSafeWorkspace, undoConsolidatedCommit } from '../src/main/git-safe-loop';

const exec = promisify(execFile);
let projectDir: string;

async function git(cwd: string, args: string[]): Promise<string> { return (await exec('git', ['-C', cwd, ...args])).stdout.trim(); }

async function initProject(): Promise<string> {
  const dir = mkdtempSync(join(tmpdir(), 'warden-safe-loop-'));
  await git(dir, ['init', '-q', '-b', 'main']);
  await git(dir, ['config', 'user.email', 'test@warden.local']);
  await git(dir, ['config', 'user.name', 'Warden Test']);
  writeFileSync(join(dir, 'README.md'), 'hello\n');
  await git(dir, ['add', '.']);
  await git(dir, ['commit', '-q', '-m', 'initial commit']);
  return dir;
}

beforeEach(async () => { projectDir = await initProject(); });
afterEach(() => { rmSync(projectDir, { recursive: true, force: true }); });

describe('isCleanGitProject', () => {
  it('reports clean for a fresh commit', async () => {
    expect(await isCleanGitProject(projectDir)).toEqual({ isGit: true, clean: true });
  });
  it('reports not-git for a plain folder', async () => {
    const plain = mkdtempSync(join(tmpdir(), 'warden-plain-'));
    try { expect(await isCleanGitProject(plain)).toEqual({ isGit: false, clean: false }); }
    finally { rmSync(plain, { recursive: true, force: true }); }
  });
  it('reports dirty when there are uncommitted changes', async () => {
    writeFileSync(join(projectDir, 'README.md'), 'changed\n');
    expect((await isCleanGitProject(projectDir)).clean).toBe(false);
  });
});

describe('startSafeWorkspace', () => {
  it('creates an isolated worktree on a warden/task branch, leaving the project untouched', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    expect(workspace.status).toBe('active');
    expect(workspace.branch).toMatch(/^warden\/task-/);
    expect(readFileSync(join(workspace.worktreePath, 'README.md'), 'utf8')).toBe('hello\n');
    // the real project's HEAD is untouched
    expect(await git(projectDir, ['rev-parse', 'HEAD'])).toBe(workspace.baseCommit);
    await discardSafeWorkspace(projectDir, workspace);
  });

  it('refuses to start on a dirty project', async () => {
    writeFileSync(join(projectDir, 'README.md'), 'dirty\n');
    await expect(startSafeWorkspace(projectDir)).rejects.toThrow(GitSafeLoopError);
  });

  it('refuses to start on a non-Git folder', async () => {
    const plain = mkdtempSync(join(tmpdir(), 'warden-plain-'));
    try { await expect(startSafeWorkspace(plain)).rejects.toThrow(GitSafeLoopError); }
    finally { rmSync(plain, { recursive: true, force: true }); }
  });
});

describe('keepSafeWorkspace / discardSafeWorkspace / undoConsolidatedCommit', () => {
  it('keep: consolidates worktree changes into one saved version on the real project, never pushes, cleans up the worktree', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    writeFileSync(join(workspace.worktreePath, 'README.md'), 'hello from the agent\n');
    await git(workspace.worktreePath, ['add', '.']);
    await git(workspace.worktreePath, ['commit', '-q', '-m', 'agent change']);

    const kept = await keepSafeWorkspace(projectDir, workspace, 'Warden update: test change');
    expect(kept.status).toBe('kept');
    expect(kept.consolidatedCommit).toBeTruthy();
    expect(readFileSync(join(projectDir, 'README.md'), 'utf8')).toBe('hello from the agent\n');

    // exactly one new commit landed on the real project (squashed)
    const log = await git(projectDir, ['log', '--oneline', `${workspace.baseCommit}..HEAD`]);
    expect(log.split('\n').filter(Boolean)).toHaveLength(1);

    // worktree was cleaned up
    const worktrees = await git(projectDir, ['worktree', 'list']);
    expect(worktrees).not.toContain(workspace.worktreePath);
  });

  it('keep: captures normal uncommitted agent edits, untracked files, and deletions', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    writeFileSync(join(workspace.worktreePath, 'README.md'), 'uncommitted agent edit\n');
    writeFileSync(join(workspace.worktreePath, 'new-file.txt'), 'new\n');

    const kept = await keepSafeWorkspace(projectDir, workspace, 'Warden update: working tree');
    expect(kept.status).toBe('kept');
    expect(readFileSync(join(projectDir, 'README.md'), 'utf8')).toBe('uncommitted agent edit\n');
    expect(readFileSync(join(projectDir, 'new-file.txt'), 'utf8')).toBe('new\n');
    expect(await git(projectDir, ['status', '--porcelain'])).toBe('');
  });

  it('keep: does not require Git identity in the project configuration', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    writeFileSync(join(workspace.worktreePath, 'README.md'), 'identity-independent\n');
    await git(projectDir, ['config', '--unset', 'user.email']);
    await git(projectDir, ['config', '--unset', 'user.name']);

    const kept = await keepSafeWorkspace(projectDir, workspace, 'Warden update without local identity');
    expect(kept.status).toBe('kept');
    expect(readFileSync(join(projectDir, 'README.md'), 'utf8')).toBe('identity-independent\n');
  });

  it('keep: stops and explains instead of forcing when the original project changed underneath it (conflict, not force)', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    writeFileSync(join(workspace.worktreePath, 'README.md'), 'agent change\n');
    await git(workspace.worktreePath, ['add', '.']);
    await git(workspace.worktreePath, ['commit', '-q', '-m', 'agent change']);

    // simulate the user editing the real project while the task ran
    writeFileSync(join(projectDir, 'other.txt'), 'user edit\n');
    await git(projectDir, ['add', '.']);
    await git(projectDir, ['commit', '-q', '-m', 'user edit']);

    const result = await keepSafeWorkspace(projectDir, workspace, 'Warden update');
    expect(result.status).toBe('conflict');
    expect(result.conflictDetail).toBeTruthy();
    // the real project's own commit is untouched/not overwritten
    expect(await git(projectDir, ['log', '-1', '--format=%s'])).toBe('user edit');
  });

  it('keep: is a no-op (discarded) when the agent made no changes', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    const result = await keepSafeWorkspace(projectDir, workspace, 'Warden update');
    expect(result.status).toBe('discarded');
    expect(await git(projectDir, ['worktree', 'list'])).not.toContain(workspace.worktreePath);
  });

  it('discard: tears down the worktree only, leaves the real project byte-for-byte unchanged', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    writeFileSync(join(workspace.worktreePath, 'README.md'), 'agent change\n');
    await git(workspace.worktreePath, ['add', '.']);
    await git(workspace.worktreePath, ['commit', '-q', '-m', 'agent change']);

    const beforeHead = await git(projectDir, ['rev-parse', 'HEAD']);
    const discarded = await discardSafeWorkspace(projectDir, workspace);
    expect(discarded.status).toBe('discarded');
    expect(await git(projectDir, ['rev-parse', 'HEAD'])).toBe(beforeHead);
    expect(readFileSync(join(projectDir, 'README.md'), 'utf8')).toBe('hello\n');
  });

  it('undo: reverts the consolidated commit via a reversible inverse, never a destructive reset', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    writeFileSync(join(workspace.worktreePath, 'README.md'), 'agent change\n');
    await git(workspace.worktreePath, ['add', '.']);
    await git(workspace.worktreePath, ['commit', '-q', '-m', 'agent change']);
    const kept = await keepSafeWorkspace(projectDir, workspace, 'Warden update');

    const undone = await undoConsolidatedCommit(projectDir, kept);
    expect(undone.status).toBe('undone');
    expect(undone.undoCommit).toBeTruthy();
    expect(readFileSync(join(projectDir, 'README.md'), 'utf8')).toBe('hello\n');

    // history still contains both the update and its revert — not erased
    const subjects = (await git(projectDir, ['log', '--format=%s'])).split('\n');
    expect(subjects).toContain('Warden update');
    expect(subjects.some((s) => s.toLowerCase().includes('revert'))).toBe(true);
  });

  it('undo: refuses when there is nothing kept yet', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    await expect(undoConsolidatedCommit(projectDir, workspace)).rejects.toThrow(GitSafeLoopError);
    await discardSafeWorkspace(projectDir, workspace);
  });

  it('undo: refuses a dirty real project so unrelated user changes are never committed', async () => {
    const workspace = await startSafeWorkspace(projectDir);
    writeFileSync(join(workspace.worktreePath, 'README.md'), 'agent change\n');
    const kept = await keepSafeWorkspace(projectDir, workspace, 'Warden update');
    writeFileSync(join(projectDir, 'user-work.txt'), 'do not commit me\n');
    await expect(undoConsolidatedCommit(projectDir, kept)).rejects.toThrow('Save or discard current project changes');
    expect(await git(projectDir, ['status', '--porcelain'])).toContain('user-work.txt');
  });
});
