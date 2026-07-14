import { app, BrowserWindow, dialog, ipcMain, session, shell, WebContentsView } from 'electron';
import { join } from 'node:path';
import type { ProviderId, ProviderStatus } from '../shared/types';
import { providerIds } from '../shared/types';
import { isAllowedProviderUrl, PROVIDERS } from './providers';
import { StateStore } from './state-store';
import { TerminalManager } from './terminal-manager';

let mainWindow: BrowserWindow | null = null;
let store: StateStore;
let terminals: TerminalManager;
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
}
function createWindow(): void {
  const bounds = store.state.windowBounds;
  mainWindow = new BrowserWindow({ ...bounds, minWidth: 1024, minHeight: 700, backgroundColor: '#0d100e', autoHideMenuBar: true, webPreferences: { preload: join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  terminals = new TerminalManager(mainWindow, store);
  void mainWindow.loadFile(join(__dirname, 'index.html'));
  if (process.argv.includes('--warden-desk-smoke')) {
    mainWindow.webContents.once('did-finish-load', () => {
      console.log('WARDEN_DESK_SMOKE renderer-ready');
      const terminal = terminals.create({ name: 'Smoke terminal', cwd: process.cwd() });
      terminals.write(terminal.id, "printf 'WARDEN_DESK_SMOKE pty-ready\\n'\n");
      setTimeout(() => { terminals.kill(terminal.id); console.log('WARDEN_DESK_SMOKE complete'); app.quit(); }, 800);
    });
  }
  mainWindow.on('close', () => { if (mainWindow) store.patch({ windowBounds: mainWindow.getBounds() }); terminals.shutdown(); });
  mainWindow.on('closed', () => { mainWindow = null; activeView = null; views.clear(); });
}

app.whenReady().then(() => { store = new StateStore(app.getPath('userData')); registerIpc(); createWindow(); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
