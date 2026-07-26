import { basename } from 'node:path';
import { BrowserWindow, dialog, Menu, session, shell, WebContentsView } from 'electron';
import type { PlatformNavigationDecision, PlatformStatus, WebPlatform } from '../shared/types';
import { PlatformAuditLog, safeLocation, safeMessageFingerprint } from './platform-audit';
import { clampMenuAnchor, classifyNavigation, decisionFromButton, popupWebPreferences } from './oauth-policy';
import { isTrustedPlatformUrl, normalizePlatformUrl, platformStorageOrigins, profilePartition } from './web-platforms';
import type { StateStore } from './state-store';

type ContentsKind = 'main' | 'popup';
type MenuAction = 'settings' | 'split' | 'refresh' | 'removed' | 'cleared';

export class PlatformManager {
  private readonly views = new Map<string, WebContentsView>();
  private readonly viewProfiles = new Map<string, string>();
  private readonly allowOnce = new Map<string, Set<string>>();
  private readonly contentPlatforms = new Map<number, string>();
  private readonly configuredSessions = new Set<string>();
  private readonly audit: PlatformAuditLog;
  private activeMenu: Menu | null = null;
  private activeIds: string[] = [];
  private bounds = { x: 232, y: 38, width: 1000, height: 700 };

  constructor(private readonly window: BrowserWindow, private readonly store: StateStore, userData: string) { this.audit = new PlatformAuditLog(userData); }

  auditFile(): string { return this.audit.file; }
  activePlatformIds(): string[] { return [...this.activeIds]; }
  private definition(id: string): WebPlatform { const platform = this.store.state.platforms.find((item) => item.id === id); if (!platform) throw new Error('Platform not found.'); if (!platform.enabled) throw new Error(`${platform.name} is disabled.`); return platform; }
  private sendStatus(id: string, patch: Partial<PlatformStatus> = {}): void { const platform = this.store.state.platforms.find((item) => item.id === id); const web = this.views.get(id)?.webContents; if (!platform) return; this.window.webContents.send('platform:status', { id, loading: web?.isLoading() || false, canGoBack: web?.navigationHistory.canGoBack() || false, canGoForward: web?.navigationHistory.canGoForward() || false, title: web?.getTitle() || platform.name, url: web?.getURL() || platform.startUrl, ...patch } satisfies PlatformStatus); }
  private sendMenuAction(action: MenuAction, platformId: string): void { if (!this.window.isDestroyed()) this.window.webContents.send('platform:menu-action', { action, platformId }); }

  private configureSession(platform: WebPlatform, web: Electron.WebContents): void {
    const partition = profilePartition(platform.browserProfileId); if (this.configuredSessions.has(partition)) return; this.configuredSessions.add(partition); const target = web.session;
    target.setPermissionCheckHandler((contents, permission) => { const platformId = contents ? this.contentPlatforms.get(contents.id) : undefined; this.audit.record({ event: 'permission.check.denied', platformId, profileId: platform.browserProfileId, partition, contentsId: contents?.id, permission }); return false; });
    target.setPermissionRequestHandler((contents, permission, callback) => { const platformId = this.contentPlatforms.get(contents.id); this.audit.record({ event: 'permission.request.denied', platformId, profileId: platform.browserProfileId, partition, contentsId: contents.id, permission }); callback(false); });
    target.on('will-download', (_event, item, source) => { const platformId = this.contentPlatforms.get(source.id); if (!platformId) return; item.pause(); const owner = BrowserWindow.fromWebContents(source) || this.window; void dialog.showSaveDialog(owner, { title: `Approve download from ${this.definition(platformId).name}`, defaultPath: basename(item.getFilename()) }).then((result) => { this.audit.record({ event: 'download.decision', platformId, contentsId: source.id, outcome: result.canceled ? 'cancel' : 'save' }); if (result.canceled || !result.filePath) item.cancel(); else { item.setSavePath(result.filePath); item.resume(); } }); });
  }

  private promptDecision(platform: WebPlatform, host: string, reason: 'navigation' | 'popup', owner: BrowserWindow): PlatformNavigationDecision {
    this.audit.record({ event: 'trust.prompt.opened', platformId: platform.id, profileId: platform.browserProfileId, host, outcome: reason });
    const response = dialog.showMessageBoxSync(owner, { type: 'question', title: 'New sign-in domain', message: `${platform.name} wants to ${reason === 'popup' ? 'open a sign-in window at' : 'continue authentication at'} ${host}.`, detail: 'Allowing this domain only permits navigation inside this sandboxed web platform. It does not grant filesystem, terminal, Brain, IPC, token, or structured-provider access.', buttons: ['Allow once', 'Trust for this platform', 'Open in system browser', 'Cancel'], defaultId: 1, cancelId: 3, noLink: true });
    const decision = decisionFromButton(response); this.audit.record({ event: 'trust.prompt.closed', platformId: platform.id, profileId: platform.browserProfileId, host, outcome: decision }); return decision;
  }
  private decideNavigation(platform: WebPlatform, rawUrl: string, reason: 'navigation' | 'popup', owner: BrowserWindow): { allow: boolean; normalized?: string; outcome: string } {
    const allowed = this.allowOnce.get(platform.id); const classified = classifyNavigation(platform, rawUrl, allowed, process.env.NODE_ENV === 'development');
    if (classified.forbidden || !classified.normalized || !classified.host) return { allow: false, outcome: 'forbidden' };
    if (classified.trusted) return { allow: true, normalized: classified.normalized, outcome: 'trusted' };
    const decision = this.promptDecision(platform, classified.host, reason, owner);
    if (decision === 'trust') this.store.updatePlatform(platform.id, { trustedAuthDomains: [...new Set([...platform.trustedAuthDomains, classified.host])] });
    if (decision === 'allow_once') { const once = this.allowOnce.get(platform.id) || new Set<string>(); once.add(classified.host); this.allowOnce.set(platform.id, once); }
    if (decision === 'external') setImmediate(() => void shell.openExternal(classified.normalized!));
    return { allow: decision === 'trust' || decision === 'allow_once', normalized: classified.normalized, outcome: decision };
  }

  private secureContents(platformId: string, web: Electron.WebContents, kind: ContentsKind): void {
    const platform = this.definition(platformId); const partition = profilePartition(platform.browserProfileId); const contentsId = web.id; this.contentPlatforms.set(contentsId, platformId); this.configureSession(platform, web);
    this.audit.record({ event: 'contents.secured', platformId, profileId: platform.browserProfileId, partition, contentsId, popup: kind === 'popup' });
    const guard = (event: Electron.Event, url: string, _isInPlace: boolean, isMainFrame: boolean): void => { const active = this.definition(platformId); const owner = BrowserWindow.fromWebContents(web) || this.window; const decision = this.decideNavigation(active, url, 'navigation', owner); this.audit.record({ event: 'navigation.will', platformId, profileId: active.browserProfileId, partition, contentsId: web.id, popup: kind === 'popup', mainFrame: isMainFrame, ...safeLocation(url), outcome: decision.outcome }); if (!decision.allow) event.preventDefault(); };
    web.on('will-navigate', guard); web.on('will-redirect', guard);
    web.on('did-start-navigation', (details) => { this.audit.record({ event: 'navigation.started', platformId, profileId: platform.browserProfileId, partition, contentsId: web.id, popup: kind === 'popup', mainFrame: details.isMainFrame, ...safeLocation(details.url) }); });
    web.on('did-redirect-navigation', (details) => { this.audit.record({ event: 'navigation.redirected', platformId, profileId: platform.browserProfileId, partition, contentsId: web.id, popup: kind === 'popup', mainFrame: details.isMainFrame, ...safeLocation(details.url) }); });
    web.on('did-fail-load', (_event, code, _description, url, isMainFrame) => { if (code !== -3) { this.audit.record({ event: 'navigation.failed', platformId, profileId: platform.browserProfileId, partition, contentsId: web.id, popup: kind === 'popup', mainFrame: isMainFrame, ...safeLocation(url), errorCode: code }); if (isMainFrame) this.sendStatus(platformId, { error: `Page failed to load (${code}) at ${safeLocation(url).host || 'unknown host'}.` }); } });
    web.on('console-message', (details) => { if (details.level !== 'warning' && details.level !== 'error') return; this.audit.record({ event: 'console.error', platformId, profileId: platform.browserProfileId, partition, contentsId: web.id, popup: kind === 'popup', consoleLevel: details.level, ...safeLocation(details.sourceId), ...safeMessageFingerprint(details.message) }); });
    web.setWindowOpenHandler(({ url }) => {
      const active = this.definition(platformId); const owner = BrowserWindow.fromWebContents(web) || this.window; const decision = this.decideNavigation(active, url, 'popup', owner);
      this.audit.record({ event: 'popup.requested', platformId, profileId: active.browserProfileId, partition, contentsId: web.id, ...safeLocation(url), outcome: decision.outcome });
      if (!decision.allow) return { action: 'deny' };
      return { action: 'allow', overrideBrowserWindowOptions: { parent: this.window, show: true, autoHideMenuBar: true, width: 720, height: 820, minWidth: 480, minHeight: 540, backgroundColor: '#0c0b0f', webPreferences: popupWebPreferences(partition) } };
    });
    web.on('did-create-window', (child, details) => { this.secureContents(platformId, child.webContents, 'popup'); child.setMenuBarVisibility(false); child.show(); child.focus(); const childContentsId = child.webContents.id; this.audit.record({ event: 'popup.created', platformId, profileId: platform.browserProfileId, partition, contentsId: childContentsId, popup: true, ...safeLocation(details.url), outcome: child.isVisible() ? 'visible' : 'hidden' }); child.on('closed', () => { this.contentPlatforms.delete(childContentsId); this.audit.record({ event: 'popup.closed', platformId, profileId: platform.browserProfileId, partition, contentsId: childContentsId, popup: true }); if (!this.window.isDestroyed()) { this.window.show(); this.window.focus(); } }); });
    web.on('destroyed', () => this.contentPlatforms.delete(contentsId));
  }

  private createView(id: string): WebContentsView {
    const platform = this.definition(id); const partition = profilePartition(platform.browserProfileId); const view = new WebContentsView({ webPreferences: popupWebPreferences(partition) }); this.secureContents(id, view.webContents, 'main');
    view.webContents.on('did-start-loading', () => this.sendStatus(id)); view.webContents.on('did-stop-loading', () => this.sendStatus(id)); view.webContents.on('page-title-updated', () => this.sendStatus(id));
    view.webContents.on('did-navigate', (_event, url) => { try { if (isTrustedPlatformUrl(this.definition(id), url, this.allowOnce.get(id))) this.store.updatePlatform(id, { lastUrl: url }); } catch { /* platform may have been removed */ } this.sendStatus(id); });
    void view.webContents.loadURL(platform.lastUrl && isTrustedPlatformUrl(platform, platform.lastUrl) ? platform.lastUrl : platform.startUrl); this.views.set(id, view); this.viewProfiles.set(id, platform.browserProfileId); return view;
  }
  private getView(id: string): WebContentsView { const platform = this.definition(id); const existing = this.views.get(id); if (existing && this.viewProfiles.get(id) === platform.browserProfileId && !existing.webContents.isDestroyed()) return existing; if (existing) { this.detach(id); existing.webContents.close(); this.views.delete(id); } return this.createView(id); }
  private layout(): void { const views = this.activeIds.map((id) => this.views.get(id)).filter((view): view is WebContentsView => Boolean(view)); if (views.length <= 1) { views[0]?.setBounds(this.bounds); return; } const left = Math.floor(this.bounds.width / 2); views[0].setBounds({ ...this.bounds, width: left }); views[1].setBounds({ x: this.bounds.x + left, y: this.bounds.y, width: this.bounds.width - left, height: this.bounds.height }); }
  private detach(id: string): void { const view = this.views.get(id); if (view) { try { this.window.contentView.removeChildView(view); } catch { /* already detached */ } } this.activeIds = this.activeIds.filter((item) => item !== id); }
  private movePlatform(id: string, direction: -1 | 1): void { const ordered = [...this.store.state.platforms].sort((a, b) => a.order - b.order); const index = ordered.findIndex((item) => item.id === id); const current = ordered[index]; const swap = ordered[index + direction]; if (!current || !swap) return; this.store.updatePlatform(current.id, { order: swap.order }); this.store.updatePlatform(swap.id, { order: current.order }); this.sendMenuAction('refresh', id); }

  show(id: string, splitId?: string): void { const primary = this.definition(id); if (!primary.allowMainView) throw new Error(`${primary.name} is not available in the main view.`); this.hide(); const ids = [id]; if (splitId && splitId !== id) { const secondary = this.definition(splitId); if (!primary.allowSplitView || !secondary.allowSplitView) throw new Error('One of these platforms does not allow split view.'); ids.push(splitId); } for (const platformId of ids) this.window.contentView.addChildView(this.getView(platformId)); this.activeIds = ids; this.layout(); this.store.patch({ selectedPlatformId: id, workspace: 'chat' }); for (const platformId of ids) this.sendStatus(platformId); }
  hide(): void { for (const id of [...this.activeIds]) this.detach(id); }
  setBounds(bounds: { x: number; y: number; width: number; height: number }): void { this.bounds = { x: Math.max(0, bounds.x), y: Math.max(0, bounds.y), width: Math.max(1, bounds.width), height: Math.max(1, bounds.height) }; this.layout(); }
  action(id: string, action: 'back' | 'forward' | 'reload' | 'stop' | 'home'): void { const web = this.getView(id).webContents; if (action === 'back' && web.navigationHistory.canGoBack()) web.navigationHistory.goBack(); if (action === 'forward' && web.navigationHistory.canGoForward()) web.navigationHistory.goForward(); if (action === 'reload') web.reload(); if (action === 'stop') web.stop(); if (action === 'home') void web.loadURL(this.definition(id).startUrl); }
  async openExternal(id: string): Promise<void> { const platform = this.definition(id); const current = this.views.get(id)?.webContents.getURL() || platform.startUrl; await shell.openExternal(normalizePlatformUrl(current, process.env.NODE_ENV === 'development')); }
  async showMenu(id: string, anchor: { x: number; y: number }): Promise<void> {
    if (this.activeIds[0] !== id) throw new Error('The menu target is not the active platform.'); const platform = this.definition(id); const profile = this.store.state.browserProfiles.find((item) => item.id === platform.browserProfileId); const ordered = [...this.store.state.platforms].sort((a, b) => a.order - b.order); const index = ordered.findIndex((item) => item.id === id); const builtIn = ['platform-claude', 'platform-chatgpt', 'platform-gemini', 'platform-grok'].includes(id);
    const menu = Menu.buildFromTemplate([
      { label: 'Home', click: () => this.action(id, 'home') }, { label: 'Reload', accelerator: 'CommandOrControl+R', click: () => this.action(id, 'reload') }, { label: 'Open in system browser', click: () => void this.openExternal(id) },
      { type: 'separator' }, { label: 'Open split view…', enabled: platform.allowSplitView && this.store.state.platforms.some((item) => item.id !== id && item.enabled && item.allowSplitView), click: () => { this.hide(); this.sendMenuAction('split', id); } }, { label: 'Platform settings…', click: () => { this.hide(); this.sendMenuAction('settings', id); } },
      { label: 'Move up', enabled: index > 0, click: () => this.movePlatform(id, -1) }, { label: 'Move down', enabled: index >= 0 && index < ordered.length - 1, click: () => this.movePlatform(id, 1) },
      { type: 'separator' }, { label: 'Clear this site’s data…', click: () => { void (async () => { const active = [...this.activeIds]; const response = await dialog.showMessageBox(this.window, { type: 'warning', title: 'Clear this site’s data?', message: `Clear configured site data for ${platform.name}?`, detail: `This signs you out by clearing configured origins in the shared “${profile?.name || 'unknown'}” Warden profile. Chromium cookies are registrable-domain scoped, so related sites in this profile can also be affected. The profile itself and Chrome data are not deleted.`, buttons: ['Clear configured site data', 'Cancel'], defaultId: 1, cancelId: 1, noLink: true }); if (response.response !== 0) return; await this.clearSiteData(id); if (active[0]) this.show(active[0], active[1]); this.sendMenuAction('cleared', id); })(); } },
      ...(builtIn ? [] : [{ label: 'Remove platform…', click: () => { void (async () => { const response = await dialog.showMessageBox(this.window, { type: 'warning', title: 'Remove platform?', message: `Remove ${platform.name} from Warden?`, detail: 'The platform definition moves to the restore list. Browser profile data, cookies, and login state are not deleted.', buttons: ['Remove platform', 'Cancel'], defaultId: 1, cancelId: 1, noLink: true }); if (response.response !== 0) return; this.remove(id); this.sendMenuAction('removed', id); })(); } }] as Electron.MenuItemConstructorOptions[]),
    ]);
    const bounds = this.window.getContentBounds(); const position = clampMenuAnchor(anchor, bounds); this.activeMenu?.closePopup(this.window); this.activeMenu = menu;
    this.audit.record({ event: 'menu.opened', platformId: id, profileId: platform.browserProfileId, anchorX: position.x, anchorY: position.y, windowWidth: bounds.width, windowHeight: bounds.height, outcome: this.window.isMaximized() ? 'maximized' : 'windowed' });
    await new Promise<void>((resolve) => menu.popup({ window: this.window, x: position.x, y: position.y, callback: resolve }));
    if (this.activeMenu === menu) this.activeMenu = null; this.audit.record({ event: 'menu.closed', platformId: id, profileId: platform.browserProfileId });
  }
  closeMenu(): void { this.activeMenu?.closePopup(this.window); }
  async clearSiteData(id: string): Promise<void> { const platform = this.definition(id); this.detach(id); const view = this.views.get(id); if (view) { view.webContents.close(); this.views.delete(id); this.viewProfiles.delete(id); } const target = session.fromPartition(profilePartition(platform.browserProfileId)); for (const origin of platformStorageOrigins(platform)) await target.clearStorageData({ origin }); this.sendStatus(id, { cleared: true, title: platform.name }); }
  remove(id: string): void { this.detach(id); const view = this.views.get(id); if (view) view.webContents.close(); this.views.delete(id); this.viewProfiles.delete(id); this.allowOnce.delete(id); this.store.removePlatform(id); }
  shutdown(): void { this.closeMenu(); this.hide(); for (const view of this.views.values()) if (!view.webContents.isDestroyed()) view.webContents.close(); this.views.clear(); }
}
