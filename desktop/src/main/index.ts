import { app, BrowserWindow, dialog, globalShortcut, Menu, nativeImage, Tray, ipcMain } from 'electron';
import { join } from 'node:path';
import { readFileSync, rmSync, writeFileSync } from 'node:fs';
import type { WebPlatform } from '../shared/types';
import { StateStore } from './state-store';
import { TerminalManager } from './terminal-manager';
import { RunManager } from './run-manager';
import { PlatformManager } from './platform-manager';
import { ServerSupervisor } from './server-supervisor';
import { PLATFORM_PRESETS, presetInput } from './web-platforms';
import { initializeGitRepository } from './git-safe-loop';
import { startOAuthSmokeFixture } from './oauth-smoke';

let mainWindow: BrowserWindow | null = null;
let store: StateStore;
let terminals: TerminalManager;
let runs: RunManager;
let platforms: PlatformManager;
let supervisor: ServerSupervisor;
let tray: Tray | null = null;
let isQuitting = false;
app.enableSandbox();

function stringId(value: unknown): value is string { return typeof value === 'string' && /^[\w-]{1,120}$/.test(value); }
function requireMainRenderer(event: Electron.IpcMainInvokeEvent): void { if (!mainWindow || event.sender.id !== mainWindow.webContents.id || event.senderFrame?.url !== mainWindow.webContents.getURL()) throw new Error('Untrusted IPC sender.'); }
function registerIpc(): void {
  ipcMain.handle('app:info', (event) => { requireMainRenderer(event); return { name: 'Warden AI Desk', version: app.getVersion(), platform: process.platform, arch: process.arch }; });
  ipcMain.handle('warden:server-health', () => supervisor.isHealthy());
  ipcMain.handle('warden:server-status', () => supervisor.getStatus());
  ipcMain.handle('warden:ensure-server', () => supervisor.ensureRunning());
  ipcMain.handle('state:get', () => ({ state: store.state, warning: store.warning }));
  ipcMain.handle('state:update', (_event, patch: unknown) => { if (!patch || typeof patch !== 'object') throw new Error('Invalid state update.'); const value = patch as Record<string, unknown>; const clean: Record<string, unknown> = {}; if (value.workspace === 'team-chat' || value.workspace === 'chat' || value.workspace === 'build') clean.workspace = value.workspace; if (typeof value.selectedPlatformId === 'string' && store.state.platforms.some((item) => item.id === value.selectedPlatformId)) clean.selectedPlatformId = value.selectedPlatformId; if (typeof value.activeProjectId === 'string' && store.state.projects.some((item) => item.id === value.activeProjectId)) clean.activeProjectId = value.activeProjectId; if (typeof value.onboardingComplete === 'boolean') clean.onboardingComplete = value.onboardingComplete; if (value.mode === 'simple' || value.mode === 'developer') clean.mode = value.mode; return store.patch(clean); });
  ipcMain.handle('platform:list', () => store.state.platforms.sort((a, b) => Number(b.pinned) - Number(a.pinned) || a.order - b.order));
  ipcMain.handle('platform:presets', () => PLATFORM_PRESETS);
  ipcMain.handle('platform:profiles', () => store.state.browserProfiles);
  ipcMain.handle('platform:create-profile', (_event, name: unknown) => { if (typeof name !== 'string') throw new Error('Invalid profile name.'); return store.createProfile(name); });
  ipcMain.handle('platform:rename-profile', (_event, id: unknown, name: unknown) => { if (!stringId(id) || typeof name !== 'string') throw new Error('Invalid profile update.'); return store.renameProfile(id, name); });
  ipcMain.handle('platform:remove-profile', (_event, id: unknown) => { if (!stringId(id)) throw new Error('Invalid profile ID.'); return store.removeProfile(id); });
  ipcMain.handle('platform:create', (_event, input: unknown) => { if (!input || typeof input !== 'object') throw new Error('Invalid platform definition.'); return store.createPlatform(input as Partial<WebPlatform> & { name: string; startUrl: string }); });
  ipcMain.handle('platform:add-preset', (_event, key: unknown, browserProfileId: unknown) => { if (typeof key !== 'string' || (browserProfileId !== undefined && typeof browserProfileId !== 'string')) throw new Error('Invalid preset request.'); return store.createPlatform({ ...presetInput(key), browserProfileId: browserProfileId as string | undefined }); });
  ipcMain.handle('platform:update', (_event, id: unknown, patch: unknown) => { if (!stringId(id) || !patch || typeof patch !== 'object') throw new Error('Invalid platform update.'); return store.updatePlatform(id, patch as Partial<WebPlatform>); });
  ipcMain.handle('platform:remove', (_event, id: unknown) => { if (!stringId(id)) throw new Error('Invalid platform ID.'); platforms.remove(id); });
  ipcMain.handle('platform:removed', () => store.state.removedPlatforms);
  ipcMain.handle('platform:restore', (_event, id: unknown) => { if (!stringId(id)) throw new Error('Invalid platform ID.'); return store.restorePlatform(id); });
  ipcMain.handle('platform:restore-defaults', () => { for (const preset of PLATFORM_PRESETS.slice(0, 4)) if (!store.state.platforms.some((item) => item.startUrl === preset.startUrl)) store.createPlatform(presetInput(preset.key)); return store.state.platforms; });
  ipcMain.handle('platform:show', (_event, id: unknown, splitId: unknown) => { if (!stringId(id) || (splitId !== undefined && !stringId(splitId))) throw new Error('Invalid platform selection.'); platforms.show(id, splitId as string | undefined); });
  ipcMain.handle('platform:hide', () => platforms.hide());
  ipcMain.handle('platform:action', (_event, id: unknown, action: unknown) => { if (!stringId(id) || !['back', 'forward', 'reload', 'stop', 'home'].includes(String(action))) throw new Error('Invalid platform action.'); platforms.action(id, action as 'back' | 'forward' | 'reload' | 'stop' | 'home'); });
  ipcMain.handle('platform:open-external', (_event, id: unknown) => { if (!stringId(id)) throw new Error('Invalid platform ID.'); return platforms.openExternal(id); });
  ipcMain.handle('platform:clear-site-data', (_event, id: unknown) => { if (!stringId(id)) throw new Error('Invalid platform ID.'); return platforms.clearSiteData(id); });
  ipcMain.handle('platform:show-menu', (event, id: unknown, anchor: unknown) => { requireMainRenderer(event); if (!stringId(id) || !anchor || typeof anchor !== 'object') throw new Error('Invalid menu request.'); const value = anchor as Record<string, unknown>; if (!Number.isFinite(value.x) || !Number.isFinite(value.y)) throw new Error('Invalid menu position.'); return platforms.showMenu(id, { x: Number(value.x), y: Number(value.y) }); });
  ipcMain.on('platform:set-bounds', (_event, bounds: unknown) => { if (!bounds || typeof bounds !== 'object') return; const b = bounds as Record<string, unknown>; if (![b.x, b.y, b.width, b.height].every(Number.isFinite)) return; platforms.setBounds({ x: Number(b.x), y: Number(b.y), width: Number(b.width), height: Number(b.height) }); });

  ipcMain.handle('project:list', () => store.state.projects);
  ipcMain.handle('project:create', (_event, input: unknown) => { if (!input || typeof input !== 'object') throw new Error('Invalid project request.'); const value = input as Record<string, unknown>; if (typeof value.cwd !== 'string' || (value.name !== undefined && typeof value.name !== 'string') || (value.browserProfileId !== undefined && typeof value.browserProfileId !== 'string')) throw new Error('Invalid project request.'); return store.createProject(value.cwd, value.name as string | undefined, value.browserProfileId as string | undefined); });
  ipcMain.handle('project:create-playground', async () => {
    const playgroundsDir = join(app.getPath('userData'), 'playgrounds');
    const { cwd, name, filesToCommit } = store.preparePlayground(playgroundsDir);
    try {
      await initializeGitRepository(cwd, { filesToCommit });
      return store.createProject(cwd, name);
    } catch (error) {
      rmSync(cwd, { recursive: true, force: true });
      throw error;
    }
  });
  ipcMain.handle('project:activate', (_event, id: unknown) => { if (!stringId(id)) throw new Error('Invalid project ID.'); return store.activateProject(id); });
  ipcMain.handle('project:update', (_event, id: unknown, patch: unknown) => { if (!stringId(id) || !patch || typeof patch !== 'object') throw new Error('Invalid project update.'); return store.updateProject(id, patch as never); });
  ipcMain.handle('terminal:list', () => terminals.list());
  ipcMain.handle('terminal:choose-directory', async () => { if (!mainWindow) return null; const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory', 'createDirectory'], title: 'Choose project directory' }); return result.canceled ? null : result.filePaths[0]; });
  ipcMain.handle('terminal:create', (_event, input: unknown) => { if (!input || typeof input !== 'object') throw new Error('Invalid terminal request.'); const value = input as Record<string, unknown>; if (typeof value.name !== 'string' || typeof value.cwd !== 'string' || (value.restoreId !== undefined && typeof value.restoreId !== 'string')) throw new Error('Invalid terminal request.'); const terminal = terminals.create({ name: value.name, cwd: value.cwd, restoreId: value.restoreId }); const recentProjects = [terminal.cwd, ...store.state.recentProjects.filter((item) => item !== terminal.cwd)].slice(0, 10); store.patch({ recentProjects }); return terminal; });
  ipcMain.on('terminal:write', (_event, id, data) => terminals.write(id, data));
  ipcMain.on('terminal:resize', (_event, id, cols, rows) => terminals.resize(id, cols, rows));
  ipcMain.handle('terminal:kill', (_event, id) => terminals.kill(id));
  ipcMain.handle('terminal:record-command', (_event, id, command) => terminals.recordCommand(id, command));
  ipcMain.handle('terminal:clear-history', (_event, id) => terminals.clearHistory(id));
  ipcMain.handle('runs:list', (_event, projectId: unknown) => { if (projectId !== undefined && typeof projectId !== 'string') throw new Error('Invalid project ID.'); const project = typeof projectId === 'string' ? store.state.projects.find((item) => item.id === projectId) : undefined; return runs.list(projectId as string | undefined, project?.cwd); });
  ipcMain.handle('runs:providers', () => runs.providerStatus());
  ipcMain.handle('runs:get', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.get(id); });
  ipcMain.handle('runs:preview-context', (_event, cwd: unknown) => { if (typeof cwd !== 'string') throw new Error('Invalid project directory.'); return runs.previewContext(cwd); });
  ipcMain.handle('runs:check-project', (_event, cwd: unknown) => { if (typeof cwd !== 'string') throw new Error('Invalid project directory.'); return runs.checkProject(cwd); });
  ipcMain.handle('runs:start', async (_event, input: unknown) => { if (!input || typeof input !== 'object') throw new Error('Invalid run request.'); const value = input as Record<string, unknown>; if (!['codex', 'claude', 'gemini', 'grok'].includes(String(value.provider)) || typeof value.prompt !== 'string' || typeof value.cwd !== 'string' || (value.projectId !== undefined && typeof value.projectId !== 'string') || typeof value.attachContext !== 'boolean' || !['subscription', 'api_key'].includes(String(value.authSource)) || (value.model !== undefined && typeof value.model !== 'string') || (value.apiFallbackApproved !== undefined && typeof value.apiFallbackApproved !== 'boolean') || (value.safe !== undefined && typeof value.safe !== 'boolean')) throw new Error('Invalid run request.'); const projectId = value.projectId as string | undefined; if (projectId && !store.state.projects.some((item) => item.id === projectId && item.cwd === value.cwd)) throw new Error('The selected project does not match this run directory.'); const run = await runs.start({ provider: value.provider as 'codex' | 'claude' | 'gemini' | 'grok', prompt: value.prompt, cwd: value.cwd, projectId, attachContext: value.attachContext, model: value.model as string | undefined, authSource: value.authSource as 'subscription' | 'api_key', apiFallbackApproved: value.apiFallbackApproved as boolean | undefined, safe: value.safe as boolean | undefined }); const recentCwd = run.projectCwd || run.cwd; store.patch({ recentProjects: [recentCwd, ...store.state.recentProjects.filter((item) => item !== recentCwd)].slice(0, 20) }); if (projectId) store.updateProject(projectId, { activeRunId: run.id }); return run; });
  ipcMain.handle('runs:resume', (_event, id: unknown, prompt: unknown) => { if (typeof id !== 'string' || typeof prompt !== 'string') throw new Error('Invalid resume request.'); return runs.resume(id, prompt); });
  ipcMain.handle('runs:cancel', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.cancel(id); });
  ipcMain.handle('runs:approve', (_event, runId: unknown, approvalId: unknown, decision: unknown, scope: unknown) => { if (typeof runId !== 'string' || typeof approvalId !== 'string' || !['approve', 'deny'].includes(String(decision)) || (scope !== undefined && !['once', 'session'].includes(String(scope)))) throw new Error('Invalid approval response.'); return runs.approve(runId, approvalId, decision as 'approve' | 'deny', scope as 'once' | 'session' | undefined); });
  ipcMain.handle('runs:handoff', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.handoff(id); });
  ipcMain.handle('runs:save-proof', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.saveProof(id); });
  ipcMain.handle('runs:keep', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.keep(id); });
  ipcMain.handle('runs:discard', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.discard(id); });
  ipcMain.handle('runs:undo-update', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.undoUpdate(id); });
}
function createWindow(): void {
  const bounds = store.state.windowBounds;
  mainWindow = new BrowserWindow({ ...bounds, minWidth: 1024, minHeight: 700, backgroundColor: '#0c0b0f', autoHideMenuBar: true, webPreferences: { preload: join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  terminals = new TerminalManager(mainWindow, store);
  runs = new RunManager(app.getPath('userData'), mainWindow);
  platforms = new PlatformManager(mainWindow, store, app.getPath('userData'));
  if (!tray) {
    const image = nativeImage.createFromPath(join(__dirname, 'assets', 'icon.png')).resize({ width: 22, height: 22 }); tray = new Tray(image); tray.setToolTip('Warden AI Desk'); tray.setContextMenu(Menu.buildFromTemplate([{ label: 'Show Warden', click: () => { mainWindow?.show(); mainWindow?.focus(); } }, { label: 'Hide Warden', click: () => mainWindow?.hide() }, { type: 'separator' }, { label: 'Quit', click: () => { isQuitting = true; app.quit(); } }])); tray.on('click', () => { if (!mainWindow) return; if (mainWindow.isVisible()) mainWindow.hide(); else { mainWindow.show(); mainWindow.focus(); } });
  }
  void mainWindow.loadFile(join(__dirname, 'index.html'));
  if (process.argv.includes('--warden-desk-smoke')) {
    mainWindow.webContents.once('did-finish-load', () => {
      console.log('WARDEN_DESK_SMOKE renderer-ready');
      const terminal = terminals.create({ name: 'Smoke terminal', cwd: process.cwd() });
      terminals.write(terminal.id, "printf 'WARDEN_DESK_SMOKE pty-ready\\n'\n");
      setTimeout(() => { terminals.kill(terminal.id); console.log('WARDEN_DESK_SMOKE complete'); app.quit(); }, 800);
    });
  }
  if (process.argv.includes('--warden-desk-codex-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      const cwd = process.env.WARDEN_DESK_SMOKE_CWD || process.cwd();
      try {
        console.log('WARDEN_CODEX_SMOKE starting');
        const run = await runs.start({ provider: 'codex', authSource: 'subscription', prompt: 'Read the repository README or AGENTS.md, run a harmless printf command that prints WARDEN_CODEX_STRUCTURED_OK, make no file changes, and report what you verified.', cwd, attachContext: true });
        const deadline = Date.now() + 120_000;
        const poll = setInterval(async () => {
          const current = runs.get(run.id);
          for (const approval of current.approvals.filter((item) => item.status === 'pending')) { console.log(`WARDEN_CODEX_SMOKE approving=${approval.method}`); await runs.approve(current.id, approval.id, 'approve', 'once'); }
          console.log(`WARDEN_CODEX_SMOKE status=${current.status} events=${current.events.length}`);
          if (['completed', 'failed', 'cancelled', 'interrupted'].includes(current.status) || Date.now() > deadline) {
            clearInterval(poll);
            console.log(`WARDEN_CODEX_SMOKE result=${JSON.stringify({ id: current.id, status: current.status, threadId: current.threadId, events: current.events.length, commands: current.events.filter((event) => event.type === 'command.completed').length, finalMessage: current.evidence.finalMessage, error: current.error })}`);
            app.quit();
          }
        }, 1000);
      } catch (error) { console.error(`WARDEN_CODEX_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-provider-auth-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      try { const reports = await runs.providerStatus(); console.log(`WARDEN_AUTH_SMOKE result=${JSON.stringify(reports.map(({ provider, state, source, installed, client, version, entitlement, detail, canStart, apiFallbackAvailable }) => ({ provider, state, source, installed, client, version, entitlement, detail, canStart, apiFallbackAvailable })))}`); } catch (error) { console.error(`WARDEN_AUTH_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); } finally { app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-grok-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      const cwd = process.env.WARDEN_DESK_SMOKE_CWD || process.cwd();
      try {
        const run = await runs.start({ provider: 'grok', authSource: 'subscription', prompt: 'Reply exactly WARDEN_GROK_ADAPTER_OK. Do not use tools or change files.', cwd, attachContext: false });
        const deadline = Date.now() + 90_000; const poll = setInterval(() => { const current = runs.get(run.id); console.log(`WARDEN_GROK_SMOKE status=${current.status} events=${current.events.length}`); if (['completed', 'failed', 'cancelled', 'interrupted'].includes(current.status) || Date.now() > deadline) { clearInterval(poll); console.log(`WARDEN_GROK_SMOKE result=${JSON.stringify({ id: current.id, status: current.status, sessionId: current.threadId, auth: current.auth?.source, events: current.events.length, finalMessage: current.evidence.finalMessage, error: current.error })}`); app.quit(); } }, 500);
      } catch (error) { console.error(`WARDEN_GROK_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-grok-resume-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      try {
        const previous = runs.list().find((run) => run.provider === 'grok' && run.threadId); if (!previous) throw new Error('No persisted Grok run is available to resume.');
        const resumed = await runs.resume(previous.id, 'Reply exactly WARDEN_GROK_RESUME_OK. Do not use tools or change files.'); const deadline = Date.now() + 90_000;
        const poll = setInterval(() => { const current = runs.get(resumed.id); console.log(`WARDEN_GROK_RESUME status=${current.status} events=${current.events.length}`); if (['completed', 'failed', 'cancelled', 'interrupted'].includes(current.status) || Date.now() > deadline) { clearInterval(poll); console.log(`WARDEN_GROK_RESUME result=${JSON.stringify({ id: current.id, status: current.status, sessionId: current.threadId, auth: current.auth?.source, finalMessage: current.evidence.finalMessage, error: current.error })}`); app.quit(); } }, 500);
      } catch (error) { console.error(`WARDEN_GROK_RESUME failed=${error instanceof Error ? error.stack : String(error)}`); app.quit(); }
    });
  }
  const cliSmokeArgument = process.argv.find((argument) => argument.startsWith('--warden-desk-cli-smoke='));
  if (cliSmokeArgument) {
    mainWindow.webContents.once('did-finish-load', async () => {
      const provider = cliSmokeArgument.split('=')[1] as 'claude' | 'gemini' | 'grok'; const cwd = process.env.WARDEN_DESK_SMOKE_CWD || process.cwd();
      try {
        if (!['claude', 'gemini', 'grok'].includes(provider)) throw new Error('Unsupported CLI smoke provider.');
        const run = await runs.start({ provider, authSource: 'subscription', prompt: `Reply exactly WARDEN_${provider.toUpperCase()}_CLI_ADAPTER_OK. Do not use tools or change files.`, cwd, attachContext: false }); const deadline = Date.now() + 90_000;
        const poll = setInterval(() => { const current = runs.get(run.id); if (['completed', 'failed', 'cancelled', 'interrupted'].includes(current.status) || Date.now() > deadline) { clearInterval(poll); console.log(`WARDEN_CLI_SMOKE result=${JSON.stringify({ provider, id: current.id, status: current.status, sessionId: current.threadId, auth: current.auth?.source, events: current.events.length, finalMessage: current.evidence.finalMessage, error: current.error })}`); app.quit(); } }, 500);
      } catch (error) { console.error(`WARDEN_CLI_SMOKE blocked=${provider}:${error instanceof Error ? error.message : String(error)}`); app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-codex-resume-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      try {
        const previous = runs.list()[0]; if (!previous?.threadId) throw new Error('No persisted Codex run is available to resume.');
        console.log(`WARDEN_RESUME_SMOKE previous=${previous.id} thread=${previous.threadId}`);
        const resumed = await runs.resume(previous.id, 'Confirm that this is the same preserved thread, make no file changes, and reply with WARDEN_CODEX_RESUME_OK.');
        const deadline = Date.now() + 120_000;
        const poll = setInterval(() => {
          const current = runs.get(resumed.id); console.log(`WARDEN_RESUME_SMOKE status=${current.status} events=${current.events.length}`);
          if (['completed', 'failed', 'cancelled', 'interrupted'].includes(current.status) || Date.now() > deadline) { clearInterval(poll); console.log(`WARDEN_RESUME_SMOKE result=${JSON.stringify({ id: current.id, status: current.status, threadId: current.threadId, finalMessage: current.evidence.finalMessage, error: current.error })}`); app.quit(); }
        }, 1000);
      } catch (error) { console.error(`WARDEN_RESUME_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-codex-build-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      const cwd = process.env.WARDEN_DESK_SMOKE_CWD || process.cwd();
      try {
        const run = await runs.start({ provider: 'codex', authSource: 'subscription', prompt: 'Create add.js exporting an add(a, b) function and add.test.js using node:test. Run node --test, fix any failure, and report the result. Do not commit.', cwd, attachContext: true });
        const deadline = Date.now() + 180_000;
        const poll = setInterval(async () => {
          const current = runs.get(run.id);
          for (const approval of current.approvals.filter((item) => item.status === 'pending')) { console.log(`WARDEN_BUILD_SMOKE approving=${approval.method} detail=${approval.detail}`); await runs.approve(current.id, approval.id, 'approve', 'once'); }
          console.log(`WARDEN_BUILD_SMOKE status=${current.status} events=${current.events.length}`);
          if (['completed', 'failed', 'cancelled', 'interrupted'].includes(current.status) || Date.now() > deadline) {
            clearInterval(poll); const handoff = await runs.handoff(run.id); const proof = await runs.saveProof(run.id); const final = runs.get(run.id); console.log(`WARDEN_BUILD_SMOKE result=${JSON.stringify({ id: final.id, status: final.status, approvals: final.approvals.length, changedFiles: final.evidence.changedFiles, tests: final.evidence.tests.map((test) => ({ command: test.command, exitCode: test.exitCode })), finalMessage: final.evidence.finalMessage, handoff: handoff.path, proof })}`); app.quit();
          }
        }, 750);
      } catch (error) { console.error(`WARDEN_BUILD_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-artifact-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      try { const run = runs.list()[0]; if (!run) throw new Error('No run available.'); const handoff = await runs.handoff(run.id); const proof = await runs.saveProof(run.id); const refreshed = runs.get(run.id); console.log(`WARDEN_ARTIFACT_SMOKE result=${JSON.stringify({ changedFiles: refreshed.evidence.changedFiles, diffBytes: refreshed.evidence.diff?.length || 0, tests: refreshed.evidence.tests.length, handoff: handoff.path, proof })}`); app.quit(); } catch (error) { console.error(`WARDEN_ARTIFACT_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-gui-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      await new Promise((resolve) => setTimeout(resolve, 2_500));
      const scene = process.env.WARDEN_DESK_GUI_SCENE || 'build';
      if (scene === 'platform') await mainWindow?.webContents.executeJavaScript("document.querySelector('#add-platform')?.click()");
      else await mainWindow?.webContents.executeJavaScript("document.querySelector('[data-workspace=build]')?.click(); document.querySelector('[data-execution=codex]')?.click();");
      await new Promise((resolve) => setTimeout(resolve, 1500));
      const image = await mainWindow?.capturePage(); const output = process.env.WARDEN_DESK_SCREENSHOT_PATH || '/tmp/warden-desk-gui.png'; if (image) writeFileSync(output, image.toPNG()); console.log(`WARDEN_GUI_SMOKE screenshot=${output}`); app.quit();
    });
  }
  if (process.argv.includes('--warden-desk-platform-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      try { let platform = store.state.platforms.find((item) => item.name === 'HyperAgent'); if (!platform) platform = store.createPlatform(presetInput('hyperagent')); platforms.show(platform.id); console.log(`WARDEN_PLATFORM_SMOKE result=${JSON.stringify({ id: platform.id, name: platform.name, profile: platform.browserProfileId, startUrl: platform.startUrl, trustedAuthDomains: platform.trustedAuthDomains, persisted: store.state.platforms.some((item) => item.id === platform!.id) })}`); await new Promise((resolve) => setTimeout(resolve, 2500)); const screenshot = process.env.WARDEN_DESK_SCREENSHOT_PATH; if (screenshot) { const image = await mainWindow?.capturePage(); if (image) writeFileSync(screenshot, image.toPNG()); console.log(`WARDEN_PLATFORM_SMOKE screenshot=${screenshot}`); } } catch (error) { console.error(`WARDEN_PLATFORM_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); } finally { app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-oauth-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      let fixture: Awaited<ReturnType<typeof startOAuthSmokeFixture>> | undefined;
      try {
        console.log('WARDEN_OAUTH_SMOKE phase=starting'); if (process.env.NODE_ENV !== 'development') throw new Error('OAuth smoke requires the explicit localhost development exception.'); fixture = await startOAuthSmokeFixture(); console.log('WARDEN_OAUTH_SMOKE phase=fixture-ready');
        const platform = store.createPlatform({ name: 'OAuth Fixture', startUrl: fixture.url, category: 'Other', browserProfileId: store.state.browserProfiles[0].id, trustedFirstPartyDomains: ['127.0.0.1'], trustedAuthDomains: ['127.0.0.1'] }); platforms.show(platform.id);
        console.log('WARDEN_OAUTH_SMOKE phase=platform-shown'); const deadline = Date.now() + 5_000; while (!fixture.completed() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 100)); await new Promise((resolve) => setTimeout(resolve, 300)); console.log('WARDEN_OAUTH_SMOKE phase=collecting');
        const audit = readFileSync(platforms.auditFile(), 'utf8'); const events = audit.trim().split('\n').map((line) => JSON.parse(line) as { event?: string; outcome?: string }).filter((item) => item.event?.startsWith('popup.'));
        console.log(`WARDEN_OAUTH_SMOKE result=${JSON.stringify({ completed: fixture.completed(), cookieReturned: fixture.cookieReturned(), openerPreserved: fixture.openerPreserved(), requests: fixture.requests(), popupCreatedVisible: events.some((item) => item.event === 'popup.created' && item.outcome === 'visible'), popupClosed: events.some((item) => item.event === 'popup.closed'), partition: `persist:warden-profile-${store.state.browserProfiles[0].id}`, auditContainsSecret: audit.includes('fixture-secret-code') })}`);
      } catch (error) { console.error(`WARDEN_OAUTH_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); } finally { console.log('WARDEN_OAUTH_SMOKE phase=stopping'); await fixture?.close().catch(() => undefined); app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-menu-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      try {
        const platform = store.createPlatform({ name: 'Menu Target', startUrl: 'https://example.com/', category: 'Other', browserProfileId: store.state.browserProfiles[0].id, trustedFirstPartyDomains: ['example.com'], trustedAuthDomains: [] });
        platforms.show(platform.id); mainWindow?.show(); mainWindow?.focus();
        const runCycle = async (mode: 'windowed' | 'maximized'): Promise<boolean> => {
          if (!mainWindow) throw new Error('Main window closed during menu smoke.');
          await new Promise((resolve) => setTimeout(resolve, 500)); const bounds = mainWindow.getContentBounds(); let forced = false;
          console.log(`WARDEN_MENU_SMOKE phase=${mode}-menu-open target=${platform.id} bounds=${bounds.width}x${bounds.height}`);
          const fallback = setTimeout(() => { forced = true; platforms.closeMenu(); }, 8_000);
          await platforms.showMenu(platform.id, { x: bounds.width - 18, y: 38 }); clearTimeout(fallback); return !forced;
        };
        mainWindow?.unmaximize(); mainWindow?.setSize(1024, 700); mainWindow?.center(); const windowedEscape = await runCycle('windowed');
        mainWindow?.maximize(); const maximizedEscape = await runCycle('maximized'); const audit = readFileSync(platforms.auditFile(), 'utf8'); const menuEvents = audit.trim().split('\n').map((line) => JSON.parse(line) as { event?: string; platformId?: string; outcome?: string }).filter((item) => item.event?.startsWith('menu.'));
        console.log(`WARDEN_MENU_SMOKE result=${JSON.stringify({ target: platform.id, activeTarget: store.state.selectedPlatformId, windowedEscape, maximizedEscape, opened: menuEvents.filter((item) => item.event === 'menu.opened' && item.platformId === platform.id).length, closed: menuEvents.filter((item) => item.event === 'menu.closed' && item.platformId === platform.id).length, modes: menuEvents.filter((item) => item.event === 'menu.opened' && item.platformId === platform.id).map((item) => item.outcome) })}`);
      } catch (error) { console.error(`WARDEN_MENU_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); } finally { app.quit(); }
    });
  }
  if (process.argv.includes('--warden-desk-platform-dialog-smoke')) {
    mainWindow.webContents.once('did-finish-load', async () => {
      try {
        await new Promise((resolve) => setTimeout(resolve, 2_000)); const target = store.state.platforms.find((item) => item.enabled && item.allowMainView); if (!target) throw new Error('No platform is available for the dialog smoke.'); platforms.show(target.id); await new Promise((resolve) => setTimeout(resolve, 300)); const before = platforms.activePlatformIds();
        const renderer = await mainWindow?.webContents.executeJavaScript(`(async () => { document.querySelector('#add-platform')?.click(); await new Promise((resolve) => setTimeout(resolve, 500)); const dialog = document.querySelector('#platform-dialog'); return { open: Boolean(dialog?.open), title: document.querySelector('#platform-dialog-title')?.textContent, focused: document.activeElement?.id }; })()`);
        const screenshot = process.env.WARDEN_DESK_SCREENSHOT_PATH || '/tmp/warden-platform-dialog.png'; const image = await mainWindow?.capturePage(); if (image) writeFileSync(screenshot, image.toPNG());
        console.log(`WARDEN_PLATFORM_DIALOG_SMOKE result=${JSON.stringify({ before, after: platforms.activePlatformIds(), renderer, screenshot })}`);
      } catch (error) { console.error(`WARDEN_PLATFORM_DIALOG_SMOKE failed=${error instanceof Error ? error.stack : String(error)}`); } finally { app.quit(); }
    });
  }
  mainWindow.on('close', (event) => { if (!isQuitting && !process.argv.some((argument) => argument.startsWith('--warden-desk-'))) { event.preventDefault(); mainWindow?.hide(); return; } if (mainWindow) store.patch({ windowBounds: mainWindow.getBounds() }); platforms.shutdown(); terminals.shutdown(); runs.shutdown(); supervisor?.shutdown(); });
  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(async () => {
  store = new StateStore(app.getPath('userData'));
  supervisor = new ServerSupervisor();
  void supervisor.ensureRunning();
  registerIpc();
  createWindow();
  globalShortcut.register('CommandOrControl+Alt+W', () => { if (!mainWindow) return; if (mainWindow.isVisible()) mainWindow.hide(); else { mainWindow.show(); mainWindow.focus(); } });
});
app.on('before-quit', () => { isQuitting = true; supervisor?.shutdown(); });
app.on('will-quit', () => { globalShortcut.unregisterAll(); tray?.destroy(); tray = null; supervisor?.shutdown(); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
