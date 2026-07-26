import type { PlatformNavigationDecision, WebPlatform } from '../shared/types';
import { isTrustedPlatformUrl, normalizePlatformUrl } from './web-platforms';

export const OAUTH_DECISIONS: PlatformNavigationDecision[] = ['allow_once', 'trust', 'external', 'cancel'];

export function decisionFromButton(index: number): PlatformNavigationDecision { return OAUTH_DECISIONS[index] || 'cancel'; }

export function classifyNavigation(platform: WebPlatform, rawUrl: string, allowOnce?: ReadonlySet<string>, allowLocalhost = false): { normalized?: string; host?: string; trusted: boolean; forbidden: boolean } {
  try {
    const normalized = normalizePlatformUrl(rawUrl, allowLocalhost); const host = new URL(normalized).hostname.toLowerCase();
    return { normalized, host, trusted: isTrustedPlatformUrl(platform, normalized, allowOnce), forbidden: false };
  } catch { return { trusted: false, forbidden: true }; }
}

export function popupWebPreferences(partition: string): Electron.WebPreferences {
  return { partition, contextIsolation: true, nodeIntegration: false, nodeIntegrationInWorker: false, nodeIntegrationInSubFrames: false, sandbox: true, webSecurity: true, allowRunningInsecureContent: false, spellcheck: true };
}

export function clampMenuAnchor(anchor: { x: number; y: number }, contentBounds: { width: number; height: number }): { x: number; y: number } {
  return {
    x: Math.max(0, Math.min(Math.round(anchor.x), Math.max(0, contentBounds.width - 20))),
    y: Math.max(0, Math.min(Math.round(anchor.y), Math.max(0, contentBounds.height - 20))),
  };
}
