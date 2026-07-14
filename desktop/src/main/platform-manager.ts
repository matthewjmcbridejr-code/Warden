import { randomUUID } from 'node:crypto';
import { basename } from 'node:path';
import { BrowserWindow, dialog, session, shell, WebContentsView } from 'electron';
import type { PlatformNavigationDecision, PlatformNavigationRequest, PlatformStatus, WebPlatform } from '../shared/types';
import { isTrustedPlatformUrl, normalizePlatformUrl, platformStorageOrigins, profilePartition } from './web-platforms';
import type { StateStore } from './state-store';

type PendingNavigation = { request: PlatformNavigationRequest; open(): void };

export class PlatformManager {
  private readonly views = new Map<string, WebContentsView>();
  private readonly viewProfiles = new Map<string, string>();
  private readonly allowOnce = new Map<string, Set<string>>();
  private readonly pending = new Map<string, PendingNavigation>();
  private activeIds: string[] = [];
  private bounds = { x: 248, y: 116, width: 1000, height: 700 };

  constructor(private readonly window: BrowserWindow, private readonly store: StateStore) {}

  private definition(id: string): WebPlatform { const platform = this.store.state.platforms.find((item) => item.id === id); if (!platform) throw new Error('Platform not found.'); if (!platform.enabled) throw new Error(`${platform.name} is disabled.`); return platform; }
  private sendStatus(id: string, patch: Partial<PlatformStatus> = {}): void { const platform = this.store.state.platforms.find((item) => item.id === id); const web = this.views.get(id)?.webContents; if (!platform) return; this.window.webContents.send('platform:status', { id, loading: web?.isLoading() || false, canGoBack: web?.navigationHistory.canGoBack() || false, canGoForward: web?.navigationHistory.canGoForward() || false, title: web?.getTitle() || platform.name, url: web?.getURL() || platform.startUrl, ...patch } satisfies PlatformStatus); }
  private navigationRequest(platform: WebPlatform, url: string, reason: 'navigation' | 'popup', open: () => void): void {
    let normalized: string;
    try { normalized = normalizePlatformUrl(url, process.env.NODE_ENV === 'development'); } catch (error) { this.sendStatus(platform.id, { error: error instanceof Error ? error.message : String(error) }); return; }
    const request: PlatformNavigationRequest = { requestId: randomUUID(), platformId: platform.id, platformName: platform.name, url: normalized, domain: new URL(normalized).hostname, reason };
    this.pending.set(request.requestId, { request, open });
    this.window.webContents.send('platform:navigation-request', request);
  }
  private secureContents(platformId: string, web: Electron.WebContents): void {
    web.session.setPermissionCheckHandler(() => false);
    web.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    const guard = (event: Electron.Event, url: string): void => {
      const platform = this.definition(platformId); const allowed = this.allowOnce.get(platformId) || new Set<string>();
      if (isTrustedPlatformUrl(platform, url, allowed)) return;
      event.preventDefault(); this.navigationRequest(platform, url, 'navigation', () => void web.loadURL(url));
    };
    web.on('will-navigate', guard);
    web.on('will-redirect', guard);
    web.setWindowOpenHandler(({ url }) => {
      const platform = this.definition(platformId); const allowed = this.allowOnce.get(platformId) || new Set<string>();
      if (!isTrustedPlatformUrl(platform, url, allowed)) { this.navigationRequest(platform, url, 'popup', () => void web.loadURL(url)); return { action: 'deny' }; }
      return { action: 'allow', overrideBrowserWindowOptions: { parent: this.window, autoHideMenuBar: true, webPreferences: { partition: profilePartition(platform.browserProfileId), contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true } } };
    });
    web.on('did-create-window', (child) => this.secureContents(platformId, child.webContents));
    web.session.on('will-download', (_event, item, source) => {
      if (source.id !== web.id) return;
      item.pause();
      void dialog.showSaveDialog(this.window, { title: `Approve download from ${this.definition(platformId).name}`, defaultPath: basename(item.getFilename()) }).then((result) => { if (result.canceled || !result.filePath) item.cancel(); else { item.setSavePath(result.filePath); item.resume(); } });
    });
  }
  private createView(id: string): WebContentsView {
    const platform = this.definition(id); const partition = profilePartition(platform.browserProfileId);
    const view = new WebContentsView({ webPreferences: { partition, contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true, allowRunningInsecureContent: false } });
    this.secureContents(id, view.webContents);
    view.webContents.on('did-start-loading', () => this.sendStatus(id)); view.webContents.on('did-stop-loading', () => this.sendStatus(id)); view.webContents.on('page-title-updated', () => this.sendStatus(id));
    view.webContents.on('did-navigate', (_event, url) => { try { if (isTrustedPlatformUrl(this.definition(id), url, this.allowOnce.get(id))) this.store.updatePlatform(id, { lastUrl: url }); } catch { /* platform may have been removed during navigation */ } this.sendStatus(id); });
    view.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => { if (isMainFrame && code !== -3) this.sendStatus(id, { error: `${description} (${code}) — ${url}` }); });
    void view.webContents.loadURL(platform.lastUrl && isTrustedPlatformUrl(platform, platform.lastUrl) ? platform.lastUrl : platform.startUrl);
    this.views.set(id, view); this.viewProfiles.set(id, platform.browserProfileId); return view;
  }
  private getView(id: string): WebContentsView { const platform = this.definition(id); const existing = this.views.get(id); if (existing && this.viewProfiles.get(id) === platform.browserProfileId && !existing.webContents.isDestroyed()) return existing; if (existing) { this.detach(id); existing.webContents.close(); this.views.delete(id); } return this.createView(id); }
  private layout(): void { const views = this.activeIds.map((id) => this.views.get(id)).filter((view): view is WebContentsView => Boolean(view)); if (views.length <= 1) { views[0]?.setBounds(this.bounds); return; } const left = Math.floor(this.bounds.width / 2); views[0].setBounds({ ...this.bounds, width: left }); views[1].setBounds({ x: this.bounds.x + left, y: this.bounds.y, width: this.bounds.width - left, height: this.bounds.height }); }
  private detach(id: string): void { const view = this.views.get(id); if (view) { try { this.window.contentView.removeChildView(view); } catch { /* already detached */ } } this.activeIds = this.activeIds.filter((item) => item !== id); }
  show(id: string, splitId?: string): void { const primary = this.definition(id); if (!primary.allowMainView) throw new Error(`${primary.name} is not available in the main view.`); this.hide(); const ids = [id]; if (splitId && splitId !== id) { const secondary = this.definition(splitId); if (!primary.allowSplitView || !secondary.allowSplitView) throw new Error('One of these platforms does not allow split view.'); ids.push(splitId); } for (const platformId of ids) { const view = this.getView(platformId); this.window.contentView.addChildView(view); } this.activeIds = ids; this.layout(); this.store.patch({ selectedPlatformId: id, workspace: 'chat' }); for (const platformId of ids) this.sendStatus(platformId); }
  hide(): void { for (const id of [...this.activeIds]) this.detach(id); }
  setBounds(bounds: { x: number; y: number; width: number; height: number }): void { this.bounds = { x: Math.max(0, bounds.x), y: Math.max(0, bounds.y), width: Math.max(1, bounds.width), height: Math.max(1, bounds.height) }; this.layout(); }
  action(id: string, action: 'back' | 'forward' | 'reload' | 'stop' | 'home'): void { const web = this.getView(id).webContents; if (action === 'back' && web.navigationHistory.canGoBack()) web.navigationHistory.goBack(); if (action === 'forward' && web.navigationHistory.canGoForward()) web.navigationHistory.goForward(); if (action === 'reload') web.reload(); if (action === 'stop') web.stop(); if (action === 'home') void web.loadURL(this.definition(id).startUrl); }
  async openExternal(id: string): Promise<void> { const platform = this.definition(id); const current = this.views.get(id)?.webContents.getURL() || platform.startUrl; const url = normalizePlatformUrl(current, process.env.NODE_ENV === 'development'); await shell.openExternal(url); }
  async resolveNavigation(requestId: string, decision: PlatformNavigationDecision): Promise<void> { const pending = this.pending.get(requestId); if (!pending) throw new Error('Navigation request expired.'); this.pending.delete(requestId); const { request } = pending; if (decision === 'external') { await shell.openExternal(request.url); return; } if (decision === 'cancel') return; if (decision === 'trust') { const platform = this.definition(request.platformId); this.store.updatePlatform(platform.id, { trustedAuthDomains: [...new Set([...platform.trustedAuthDomains, request.domain])] }); } else { const once = this.allowOnce.get(request.platformId) || new Set<string>(); once.add(request.domain); this.allowOnce.set(request.platformId, once); } pending.open(); }
  async clearSiteData(id: string): Promise<void> { const platform = this.definition(id); this.detach(id); const view = this.views.get(id); if (view) { view.webContents.close(); this.views.delete(id); this.viewProfiles.delete(id); } const target = session.fromPartition(profilePartition(platform.browserProfileId)); for (const origin of platformStorageOrigins(platform)) await target.clearStorageData({ origin }); this.sendStatus(id, { cleared: true, title: platform.name }); }
  remove(id: string): void { this.detach(id); const view = this.views.get(id); if (view) view.webContents.close(); this.views.delete(id); this.viewProfiles.delete(id); this.allowOnce.delete(id); this.store.removePlatform(id); }
  shutdown(): void { this.hide(); for (const view of this.views.values()) if (!view.webContents.isDestroyed()) view.webContents.close(); this.views.clear(); }
}
