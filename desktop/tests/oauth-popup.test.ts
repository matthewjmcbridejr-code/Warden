import { describe, expect, it } from 'vitest';
import type { BrowserProfile } from '../src/shared/types';
import { createPlatform, presetInput, profilePartition } from '../src/main/web-platforms';
import { clampMenuAnchor, classifyNavigation, decisionFromButton, popupWebPreferences } from '../src/main/oauth-policy';
import { safeLocation, safeMessageFingerprint } from '../src/main/platform-audit';

const profiles: BrowserProfile[] = [{ id: 'profile-oauth', name: 'OAuth', createdAt: new Date(0).toISOString() }];
const grok = createPlatform({ ...presetInput('grok'), browserProfileId: profiles[0].id }, profiles, 0);

describe('OAuth popup and navigation regression', () => {
  it('allows Google and provider callbacks while requiring a decision for new domains', () => {
    expect(classifyNavigation(grok, 'https://accounts.google.com/v3/signin/challenge/pwd?continue=secret').trusted).toBe(true);
    expect(classifyNavigation(grok, 'https://grok.com/auth/callback?code=secret').trusted).toBe(true);
    expect(classifyNavigation(grok, 'https://new-login.example.com/oauth').trusted).toBe(false);
    expect(classifyNavigation(grok, 'javascript:alert(1)').forbidden).toBe(true);
    expect(classifyNavigation(grok, 'https://new-login.example.com/oauth', new Set(['new-login.example.com'])).trusted).toBe(true);
  });

  it('maps every native trust-dialog choice without an implicit allow', () => {
    expect([0, 1, 2, 3, 99].map(decisionFromButton)).toEqual(['allow_once', 'trust', 'external', 'cancel', 'cancel']);
  });

  it('forces OAuth popups into the originating persistent profile with no privileged renderer options', () => {
    const partition = profilePartition(grok.browserProfileId); const preferences = popupWebPreferences(partition);
    expect(preferences.partition).toBe(partition); expect(preferences.contextIsolation).toBe(true); expect(preferences.sandbox).toBe(true); expect(preferences.nodeIntegration).toBe(false); expect(preferences.nodeIntegrationInWorker).toBe(false); expect(preferences.nodeIntegrationInSubFrames).toBe(false); expect(preferences.webSecurity).toBe(true); expect(preferences.allowRunningInsecureContent).toBe(false); expect(preferences.preload).toBeUndefined();
  });

  it('logs hosts and fingerprints without URL paths, queries, messages, or credentials', () => {
    expect(safeLocation('https://accounts.google.com/signin/challenge?password=never-log-this')).toEqual({ host: 'accounts.google.com', protocol: 'https:' });
    const fingerprint = safeMessageFingerprint('credential-looking console error'); expect(fingerprint.messageHash).toMatch(/^[a-f0-9]{16}$/); expect(fingerprint.messageLength).toBe(32); expect(JSON.stringify(fingerprint)).not.toContain('credential-looking');
  });

  it('keeps a native menu anchor inside resized and maximized content bounds', () => {
    expect(clampMenuAnchor({ x: 980.6, y: 38.4 }, { width: 1024, height: 700 })).toEqual({ x: 981, y: 38 });
    expect(clampMenuAnchor({ x: 5000, y: 5000 }, { width: 1920, height: 1080 })).toEqual({ x: 1900, y: 1060 });
    expect(clampMenuAnchor({ x: -10, y: -10 }, { width: 12, height: 12 })).toEqual({ x: 0, y: 0 });
  });
});
