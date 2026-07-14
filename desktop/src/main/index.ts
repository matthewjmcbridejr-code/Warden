import { app, BrowserWindow, dialog, ipcMain, session, shell, WebContentsView } from 'electron';
import { join } from 'node:path';
import { writeFileSync } from 'node:fs';
import type { ProviderId, ProviderStatus } from '../shared/types';
import { providerIds } from '../shared/types';
import { isAllowedProviderUrl, PROVIDERS } from './providers';
import { StateStore } from './state-store';
import { TerminalManager } from './terminal-manager';
import { RunManager } from './run-manager';

let mainWindow: BrowserWindow | null = null;
let store: StateStore;
let terminals: TerminalManager;
let runs: RunManager;
let activeView: WebContentsView | null = null;
let activeProvider: ProviderId | null = null;
const views = new Map<ProviderId, WebContentsView>();
let contentBounds = { x: 248, y: 116, width: 1000, height: 700 };

function validProvider(value: unknown): value is ProviderId { return providerIds.includes(value as ProviderId); }
function sendStatus(id: ProviderId, patch: Partial<ProviderStatus> = {}): void {
  const web = views.get(id)?.webContents;
  mainWindow?.webContents.send('provider:status', { id, loading: web?.isLoading() || false, canGoBack: web?.navigationHistory.canGoBack() || false, canGoForward: web?.navigationHistory.canGoForward() || false, title: web?.getTitle() || PROVIDERS[id].name, ...patch } satisfies ProviderStatus);
}
function secureContents(id: ProviderId, web: Electron.WebContents): void {
  web.session.setPermissionCheckHandler(() => false);
  web.session.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  web.on('will-navigate', (event, url) => { if (!isAllowedProviderUrl(id, url)) { event.preventDefault(); void shell.openExternal(url); } });
  web.setWindowOpenHandler(({ url }) => {
    if (!isAllowedProviderUrl(id, url)) { if (url.startsWith('https:')) void shell.openExternal(url); return { action: 'deny' }; }
    return { action: 'allow', overrideBrowserWindowOptions: { parent: mainWindow || undefined, autoHideMenuBar: true, webPreferences: { partition: PROVIDERS[id].partition, contextIsolation: true, nodeIntegration: false, sandbox: true } } };
  });
  web.on('did-create-window', (child) => secureContents(id, child.webContents));
}
function createProviderView(id: ProviderId): WebContentsView {
  const definition = PROVIDERS[id];
  const view = new WebContentsView({ webPreferences: { partition: definition.partition, contextIsolation: true, nodeIntegration: false, sandbox: true } });
  secureContents(id, view.webContents);
  view.webContents.on('did-start-loading', () => sendStatus(id));
  view.webContents.on('did-stop-loading', () => sendStatus(id));
  view.webContents.on('page-title-updated', () => sendStatus(id));
  view.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => { if (isMainFrame && code !== -3) sendStatus(id, { error: `${description} (${code}) — ${url}` }); });
  void view.webContents.loadURL(definition.homeUrl);
  views.set(id, view); return view;
}
function showProvider(id: ProviderId): void {
  if (!mainWindow) return;
  if (activeView) mainWindow.contentView.removeChildView(activeView);
  activeView = views.get(id) || createProviderView(id); activeProvider = id;
  mainWindow.contentView.addChildView(activeView); activeView.setBounds(contentBounds);
  store.patch({ selectedProvider: id, workspace: 'chat' }); sendStatus(id);
}
function hideProvider(): void { if (mainWindow && activeView) mainWindow.contentView.removeChildView(activeView); activeView = null; activeProvider = null; }
function registerIpc(): void {
  ipcMain.handle('state:get', () => ({ state: store.state, warning: store.warning }));
  ipcMain.handle('state:update', (_event, patch: unknown) => { if (!patch || typeof patch !== 'object') throw new Error('Invalid state update.'); const value = patch as Record<string, unknown>; const clean: Record<string, unknown> = {}; if (value.workspace === 'chat' || value.workspace === 'build') clean.workspace = value.workspace; if (validProvider(value.selectedProvider)) clean.selectedProvider = value.selectedProvider; return store.patch(clean); });
  ipcMain.handle('provider:show', (_event, id: unknown) => { if (!validProvider(id)) throw new Error('Unknown provider.'); showProvider(id); });
  ipcMain.handle('provider:hide', () => hideProvider());
  ipcMain.handle('provider:action', (_event, id: unknown, action: unknown) => { if (!validProvider(id) || !['back', 'forward', 'reload', 'stop', 'home'].includes(String(action))) throw new Error('Invalid provider action.'); const web = views.get(id)?.webContents; if (!web) return; if (action === 'back' && web.navigationHistory.canGoBack()) web.navigationHistory.goBack(); if (action === 'forward' && web.navigationHistory.canGoForward()) web.navigationHistory.goForward(); if (action === 'reload') web.reload(); if (action === 'stop') web.stop(); if (action === 'home') void web.loadURL(PROVIDERS[id].homeUrl); });
  ipcMain.handle('provider:clear-session', async (_event, id: unknown) => { if (!validProvider(id)) throw new Error('Unknown provider.'); if (activeProvider === id) hideProvider(); const view = views.get(id); if (view) { view.webContents.close(); views.delete(id); } const target = session.fromPartition(PROVIDERS[id].partition); await target.clearStorageData(); await target.clearCache(); sendStatus(id, { cleared: true, title: PROVIDERS[id].name }); });
  ipcMain.on('provider:set-bounds', (_event, bounds: unknown) => { if (!bounds || typeof bounds !== 'object') return; const b = bounds as Record<string, unknown>; if (![b.x, b.y, b.width, b.height].every(Number.isFinite)) return; contentBounds = { x: Math.max(0, Number(b.x)), y: Math.max(0, Number(b.y)), width: Math.max(1, Number(b.width)), height: Math.max(1, Number(b.height)) }; activeView?.setBounds(contentBounds); });
  ipcMain.handle('terminal:list', () => terminals.list());
  ipcMain.handle('terminal:choose-directory', async () => { if (!mainWindow) return null; const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory', 'createDirectory'], title: 'Choose project directory' }); return result.canceled ? null : result.filePaths[0]; });
  ipcMain.handle('terminal:create', (_event, input: unknown) => { if (!input || typeof input !== 'object') throw new Error('Invalid terminal request.'); const value = input as Record<string, unknown>; if (typeof value.name !== 'string' || typeof value.cwd !== 'string' || (value.restoreId !== undefined && typeof value.restoreId !== 'string')) throw new Error('Invalid terminal request.'); const terminal = terminals.create({ name: value.name, cwd: value.cwd, restoreId: value.restoreId }); const recentProjects = [terminal.cwd, ...store.state.recentProjects.filter((item) => item !== terminal.cwd)].slice(0, 10); store.patch({ recentProjects }); return terminal; });
  ipcMain.on('terminal:write', (_event, id, data) => terminals.write(id, data));
  ipcMain.on('terminal:resize', (_event, id, cols, rows) => terminals.resize(id, cols, rows));
  ipcMain.handle('terminal:kill', (_event, id) => terminals.kill(id));
  ipcMain.handle('terminal:record-command', (_event, id, command) => terminals.recordCommand(id, command));
  ipcMain.handle('terminal:clear-history', (_event, id) => terminals.clearHistory(id));
  ipcMain.handle('runs:list', () => runs.list());
  ipcMain.handle('runs:get', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.get(id); });
  ipcMain.handle('runs:preview-context', (_event, cwd: unknown) => { if (typeof cwd !== 'string') throw new Error('Invalid project directory.'); return runs.previewContext(cwd); });
  ipcMain.handle('runs:start', async (_event, input: unknown) => { if (!input || typeof input !== 'object') throw new Error('Invalid run request.'); const value = input as Record<string, unknown>; if (typeof value.prompt !== 'string' || typeof value.cwd !== 'string' || typeof value.attachContext !== 'boolean' || (value.model !== undefined && typeof value.model !== 'string')) throw new Error('Invalid run request.'); const run = await runs.start({ prompt: value.prompt, cwd: value.cwd, attachContext: value.attachContext, model: value.model as string | undefined }); store.patch({ recentProjects: [run.cwd, ...store.state.recentProjects.filter((item) => item !== run.cwd)].slice(0, 10) }); return run; });
  ipcMain.handle('runs:resume', (_event, id: unknown, prompt: unknown) => { if (typeof id !== 'string' || typeof prompt !== 'string') throw new Error('Invalid resume request.'); return runs.resume(id, prompt); });
  ipcMain.handle('runs:cancel', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.cancel(id); });
  ipcMain.handle('runs:approve', (_event, runId: unknown, approvalId: unknown, decision: unknown, scope: unknown) => { if (typeof runId !== 'string' || typeof approvalId !== 'string' || !['approve', 'deny'].includes(String(decision)) || (scope !== undefined && !['once', 'session'].includes(String(scope)))) throw new Error('Invalid approval response.'); return runs.approve(runId, approvalId, decision as 'approve' | 'deny', scope as 'once' | 'session' | undefined); });
  ipcMain.handle('runs:handoff', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.handoff(id); });
  ipcMain.handle('runs:save-proof', (_event, id: unknown) => { if (typeof id !== 'string') throw new Error('Invalid run ID.'); return runs.saveProof(id); });
}
function createWindow(): void {
  const bounds = store.state.windowBounds;
  mainWindow = new BrowserWindow({ ...bounds, minWidth: 1024, minHeight: 700, backgroundColor: '#0d100e', autoHideMenuBar: true, webPreferences: { preload: join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  terminals = new TerminalManager(mainWindow, store);
  runs = new RunManager(app.getPath('userData'), mainWindow);
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
        const run = await runs.start({ prompt: 'Read the repository README or AGENTS.md, run a harmless printf command that prints WARDEN_CODEX_STRUCTURED_OK, make no file changes, and report what you verified.', cwd, attachContext: true });
        const deadline = Date.now() + 120_000;
        const poll = setInterval(() => {
          const current = runs.get(run.id);
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
        const run = await runs.start({ prompt: 'Create add.js exporting an add(a, b) function and add.test.js using node:test. Run node --test, fix any failure, and report the result. Do not commit.', cwd, attachContext: true });
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
      await new Promise((resolve) => setTimeout(resolve, 800));
      await mainWindow?.webContents.executeJavaScript("document.querySelector('[data-workspace=build]')?.click(); document.querySelector('[data-execution=codex]')?.click();");
      await new Promise((resolve) => setTimeout(resolve, 800));
      const image = await mainWindow?.capturePage(); const output = process.env.WARDEN_DESK_SCREENSHOT_PATH || '/tmp/warden-desk-gui.png'; if (image) writeFileSync(output, image.toPNG()); console.log(`WARDEN_GUI_SMOKE screenshot=${output}`); app.quit();
    });
  }
  mainWindow.on('close', () => { if (mainWindow) store.patch({ windowBounds: mainWindow.getBounds() }); terminals.shutdown(); runs.shutdown(); });
  mainWindow.on('closed', () => { mainWindow = null; activeView = null; views.clear(); });
}

app.whenReady().then(() => { store = new StateStore(app.getPath('userData')); registerIpc(); createWindow(); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
