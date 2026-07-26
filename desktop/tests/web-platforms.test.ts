import { describe, expect, it } from 'vitest';
import type { BrowserProfile } from '../src/shared/types';
import { createPlatform, isTrustedPlatformUrl, normalizePlatformUrl, platformStorageOrigins, presetInput, profilePartition } from '../src/main/web-platforms';

const profiles: BrowserProfile[] = [{ id: 'profile-personal', name: 'Personal', createdAt: new Date(0).toISOString() }, { id: 'profile-work', name: 'Work', createdAt: new Date(0).toISOString() }];

describe('custom web platform security', () => {
  it('normalizes HTTPS and rejects privileged or executable schemes', () => {
    expect(normalizePlatformUrl('hyperagent.com')).toBe('https://hyperagent.com/');
    for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,x', 'chrome://settings', 'http://example.com', 'https://user:pass@example.com']) expect(() => normalizePlatformUrl(url)).toThrow();
    expect(normalizePlatformUrl('http://localhost:4173/test', true)).toBe('http://localhost:4173/test');
    expect(() => normalizePlatformUrl('http://localhost:4173/test')).toThrow();
  });

  it('adds HyperAgent through the same generic definition path as custom platforms', () => {
    const hyperagent = createPlatform({ ...presetInput('hyperagent'), browserProfileId: 'profile-work' }, profiles, 4);
    const custom = createPlatform({ name: 'Matt AI', startUrl: 'https://ai.example.com/', browserProfileId: 'profile-work' }, profiles, 5);
    expect(hyperagent.id).toMatch(/^platform-/); expect(custom.id).toMatch(/^platform-/); expect(hyperagent.browserProfileId).toBe('profile-work');
    expect(hyperagent.trustedAuthDomains).toContain('auth.hyperagent.com');
  });

  it('shares a persistent partition only when the named profile matches', () => {
    expect(profilePartition('profile-personal')).toBe(profilePartition('profile-personal'));
    expect(profilePartition('profile-personal')).not.toBe(profilePartition('profile-work'));
    expect(profilePartition('profile-work')).toBe('persist:warden-profile-profile-work');
  });

  it('requires an explicit trust decision for new domains', () => {
    const platform = createPlatform({ name: 'Example', startUrl: 'https://app.example.com/', trustedAuthDomains: ['accounts.google.com'] }, profiles, 0);
    expect(isTrustedPlatformUrl(platform, 'https://app.example.com/chat')).toBe(true);
    expect(isTrustedPlatformUrl(platform, 'https://accounts.google.com/o/oauth2/auth')).toBe(true);
    expect(isTrustedPlatformUrl(platform, 'https://evil.example.net/phish')).toBe(false);
    expect(isTrustedPlatformUrl(platform, 'https://login.example.net/start', new Set(['login.example.net']))).toBe(true);
  });

  it('scopes clearing to configured origins instead of an entire shared profile', () => {
    const platform = createPlatform({ name: 'Example', startUrl: 'https://app.example.com/', trustedFirstPartyDomains: ['example.com'], trustedAuthDomains: ['login.example.com'] }, profiles, 0);
    expect(platformStorageOrigins(platform)).toEqual(['https://app.example.com', 'https://example.com', 'https://login.example.com']);
    expect(platformStorageOrigins(platform)).not.toContain('https://unrelated.example.net');
  });
});
