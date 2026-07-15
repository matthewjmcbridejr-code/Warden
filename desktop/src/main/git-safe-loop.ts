import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import type { SafeWorkspace } from '../shared/types';

const exec = promisify(execFile);
const SAFE_ROOT = join(homedir(), '.warden', 'desktop', 'safe-workspaces');

class GitSafeLoopError extends Error {}

async function git(cwd: string, args: string[]): Promise<{ stdout: string; stderr: string }> {
  try {
    return await exec('git', ['-C', cwd, ...args], { timeout: 15_000, maxBuffer: 4 * 1024 * 1024 });
  } catch (error) {
    const stderr = (error as { stderr?: string }).stderr?.trim() || '';
    throw new GitSafeLoopError(`git ${args.join(' ')} failed${stderr ? `: ${stderr}` : ''}`);
  }
}

async function cleanupWorkspace(projectCwd: string, workspace: SafeWorkspace): Promise<void> {
  await git(projectCwd, ['worktree', 'remove', workspace.worktreePath, '--force']).catch(() => undefined);
  await git(projectCwd, ['branch', '-D', workspace.branch]).catch(() => undefined);
}

/** Step 1 — Simple Mode only accepts a clean Git-backed project. Dirty/advanced repos stay in Developer Mode. */
export async function isCleanGitProject(cwd: string): Promise<{ isGit: boolean; clean: boolean }> {
  try {
    const inside = await exec('git', ['-C', cwd, 'rev-parse', '--is-inside-work-tree'], { timeout: 5_000 });
    if (inside.stdout.trim() !== 'true') return { isGit: false, clean: false };
  } catch {
    return { isGit: false, clean: false };
  }
  const status = await exec('git', ['-C', cwd, 'status', '--porcelain'], { timeout: 5_000 });
  return { isGit: true, clean: status.stdout.trim().length === 0 };
}

/** Steps 2–3 — record the starting commit, create an isolated task worktree. */
export async function startSafeWorkspace(projectCwd: string): Promise<SafeWorkspace> {
  const { isGit, clean } = await isCleanGitProject(projectCwd);
  if (!isGit) throw new GitSafeLoopError('This project is not a Git repository. Simple Mode cannot start a safe workspace here.');
  if (!clean) throw new GitSafeLoopError('This project has unsaved changes outside Warden. Save or discard them first, or switch to Developer Mode.');

  const baseCommit = (await git(projectCwd, ['rev-parse', 'HEAD'])).stdout.trim();
  const taskId = randomUUID().slice(0, 8);
  const branch = `warden/task-${taskId}`;
  mkdirSync(SAFE_ROOT, { recursive: true });
  const worktreePath = join(SAFE_ROOT, taskId);
  await git(projectCwd, ['worktree', 'add', '-b', branch, worktreePath, baseCommit]);
  return { worktreePath, branch, baseCommit, status: 'active' };
}

/** Step 5 — verify the original project hasn't moved since the safe workspace was created. */
async function verifyUnchanged(projectCwd: string, baseCommit: string): Promise<void> {
  const { clean } = await isCleanGitProject(projectCwd);
  const head = (await git(projectCwd, ['rev-parse', 'HEAD'])).stdout.trim();
  if (!clean) throw new GitSafeLoopError('The original project changed outside Warden while this task was running. Stopping instead of forcing the update.');
  if (head !== baseCommit) throw new GitSafeLoopError('The original project moved to a different version while this task was running. Stopping instead of forcing the update.');
}

/**
 * Steps 4, 6–7 — consolidate the worktree's commits into one saved version
 * and apply it to the real project, only after Keep changes and only if the
 * original project is unchanged. Never pushes remotely (step 7).
 */
export async function keepSafeWorkspace(projectCwd: string, workspace: SafeWorkspace, summary: string): Promise<SafeWorkspace> {
  if (!['active', 'conflict'].includes(workspace.status)) throw new GitSafeLoopError('This safe workspace is no longer available to keep.');

  // Structured agents normally leave working-tree edits rather than Git
  // commits. Stage the complete isolated tree, including deletions and
  // untracked files, then synthesize one commit whose parent is the version
  // Warden started from. This never changes the real project or requires the
  // agent/client to manage Git history.
  await git(workspace.worktreePath, ['add', '--all']);
  const tree = (await git(workspace.worktreePath, ['write-tree'])).stdout.trim();
  const baseTree = (await git(workspace.worktreePath, ['rev-parse', `${workspace.baseCommit}^{tree}`])).stdout.trim();
  if (tree === baseTree) {
    await cleanupWorkspace(projectCwd, workspace);
    return { ...workspace, status: 'discarded', conflictDetail: undefined };
  }

  try {
    await verifyUnchanged(projectCwd, workspace.baseCommit);
  } catch (error) {
    const conflictDetail = error instanceof Error ? error.message : String(error);
    return { ...workspace, status: 'conflict', conflictDetail };
  }

  const message = summary.slice(0, 500) || 'Warden update';
  const synthesized = (await git(workspace.worktreePath, [
    '-c', 'user.name=Warden AI Desk',
    '-c', 'user.email=noreply@warden.local',
    'commit-tree', tree, '-p', workspace.baseCommit, '-m', message,
  ])).stdout.trim();

  // Cherry-pick is deliberately used as the transaction boundary. If a hook,
  // filter, or unexpected conflict fails, --abort restores the clean original
  // project instead of leaving a half-applied squash in its index.
  try {
    await git(projectCwd, [
      '-c', 'user.name=Warden AI Desk',
      '-c', 'user.email=noreply@warden.local',
      'cherry-pick', synthesized,
    ]);
  } catch (error) {
    await git(projectCwd, ['cherry-pick', '--abort']).catch(() => undefined);
    return { ...workspace, status: 'conflict', conflictDetail: `Warden could not apply the saved update cleanly. The original project was restored. ${error instanceof Error ? error.message : String(error)}` };
  }
  const consolidatedCommit = (await git(projectCwd, ['rev-parse', 'HEAD'])).stdout.trim();

  await cleanupWorkspace(projectCwd, workspace);

  return { ...workspace, status: 'kept', consolidatedCommit, conflictDetail: undefined };
}

/** Discard (pre-acceptance) — tears down the isolated worktree only; the original project is never touched. */
export async function discardSafeWorkspace(projectCwd: string, workspace: SafeWorkspace): Promise<SafeWorkspace> {
  await cleanupWorkspace(projectCwd, workspace);
  return { ...workspace, status: 'discarded' };
}

/**
 * Undo this update (post-acceptance) — a reversible inverse commit, never a
 * destructive reset. Safe even if the user made further changes after
 * keeping, short of them touching the exact same lines (normal git-revert
 * conflict, surfaced rather than forced).
 */
export async function undoConsolidatedCommit(projectCwd: string, workspace: SafeWorkspace): Promise<SafeWorkspace> {
  if (workspace.status !== 'kept' || !workspace.consolidatedCommit) throw new GitSafeLoopError('There is no saved update to undo for this workspace.');
  const { isGit, clean } = await isCleanGitProject(projectCwd);
  if (!isGit || !clean) throw new GitSafeLoopError('Save or discard current project changes before undoing this Warden update. Nothing was changed.');
  try {
    await git(projectCwd, ['-c', 'user.name=Warden AI Desk', '-c', 'user.email=noreply@warden.local', 'revert', '--no-edit', workspace.consolidatedCommit]);
  } catch (error) {
    await git(projectCwd, ['revert', '--abort']).catch(() => undefined);
    throw new GitSafeLoopError(`Undo could not be applied cleanly — the project has changed since then. ${error instanceof Error ? error.message : String(error)}`);
  }
  const undoCommit = (await git(projectCwd, ['rev-parse', 'HEAD'])).stdout.trim();
  return { ...workspace, status: 'undone', undoCommit };
}

export { GitSafeLoopError };
