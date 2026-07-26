import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const userData = process.argv[2];
if (!userData) throw new Error('Usage: node scripts/create-portfolio-fixture.mjs <electron-user-data>');

const now = '2026-07-14T18:00:00.000Z';
const statePath = join(userData, 'desktop-state.json');
const state = JSON.parse(await readFile(statePath, 'utf8'));
const project = {
  id: 'project-portfolio-atlas', name: 'Atlas Notes', cwd: '/tmp/warden-portfolio/atlas-notes', branch: 'feat/search-index',
  browserProfileId: 'profile-personal', selectedPlatformId: 'platform-chatgpt', workspace: 'build', executionMode: 'codex',
  terminalIds: [], activeRunId: 'run-portfolio-review', updatedAt: now,
};
state.onboardingComplete = true; state.workspace = 'build'; state.selectedPlatformId = 'platform-chatgpt'; state.activeProjectId = project.id;
state.projects = [project]; state.recentProjects = [project.cwd]; state.terminals = [];
await mkdir(project.cwd, { recursive: true });
await writeFile(statePath, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });

const runRoot = join(userData, 'runs', 'run-portfolio-review');
await mkdir(runRoot, { recursive: true });
const auth = { provider: 'codex', state: 'subscription_authenticated', source: 'subscription', installed: true, client: 'codex app-server', entitlement: 'ChatGPT subscription', detail: 'Authenticated by the official local client.', canStart: true, apiFallbackAvailable: false, checkedAt: now };
const event = (type, payload, offset) => ({ type, runId: 'run-portfolio-review', provider: 'codex', timestamp: `2026-07-14T18:0${offset}:00.000Z`, payload });
const run = {
  id: 'run-portfolio-review', provider: 'codex', project: 'Atlas Notes', projectId: project.id, cwd: project.cwd,
  prompt: '[SYNTHETIC DEMO] Add deterministic note search and prove the behavior with focused tests.', status: 'completed', auth,
  threadId: 'thread-demo-redacted', turnId: 'turn-demo-redacted', createdAt: now, updatedAt: now,
  events: [
    event('run.started', { message: 'Structured Codex thread started with subscription authentication.' }, 0),
    event('command.started', { command: 'npm test -- search-index' }, 1),
    event('command.completed', { command: 'npm test -- search-index', exitCode: 0, output: '3 focused tests passed' }, 2),
    event('approval.requested', { detail: 'Write the reviewed search index implementation to the workspace.' }, 3),
    event('file.changed', { changes: ['src/search-index.ts', 'tests/search-index.test.ts'] }, 4),
    event('run.completed', { finalMessage: 'Implemented deterministic note search; focused tests pass and the diff is ready for review.' }, 5),
  ],
  approvals: [{ id: 'approval-demo', requestId: 'request-demo', method: 'item/commandExecution/requestApproval', status: 'approved', title: 'Workspace write', detail: 'Apply the reviewed implementation in Atlas Notes.', createdAt: now, providerPayload: { synthetic: true } }],
  evidence: { branch: 'feat/search-index', gitStatusBefore: '', gitStatusAfter: ' M src/search-index.ts\n?? tests/search-index.test.ts', changedFiles: ['src/search-index.ts', 'tests/search-index.test.ts'], diff: '+ deterministic search index', tests: [{ command: 'npm test -- search-index', exitCode: 0, output: '3 focused tests passed' }], finalMessage: 'Implemented deterministic note search; focused tests pass and the diff is ready for review.' },
  proof: { local: 'saved', brain: 'saved', detail: 'Synthetic portfolio proof fixture.' },
};
await writeFile(join(runRoot, 'run.json'), `${JSON.stringify(run, null, 2)}\n`, { mode: 0o600 });
await writeFile(join(userData, 'runs', 'index.json'), `${JSON.stringify([run.id], null, 2)}\n`, { mode: 0o600 });
console.log(`Synthetic portfolio fixture created in ${userData}`);
