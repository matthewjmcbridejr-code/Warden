import { randomUUID } from 'node:crypto';
import type { BrowserProfile, PlatformPreset, WebPlatform } from '../shared/types';

const FORBIDDEN_PROTOCOLS = new Set(['file:', 'javascript:', 'data:', 'blob:', 'devtools:', 'chrome:', 'chrome-extension:', 'about:']);
const CATEGORY_VALUES = new Set(['Chat', 'Build', 'Research', 'Other']);
const AUTH_DOMAINS = ['accounts.google.com', 'appleid.apple.com', 'login.microsoftonline.com', 'github.com'];

export const PLATFORM_PRESETS: PlatformPreset[] = [
  { key: 'claude', name: 'Claude', startUrl: 'https://claude.ai/', category: 'Chat', icon: { kind: 'text', value: 'CL' }, trustedFirstPartyDomains: ['claude.ai', 'anthropic.com'], trustedAuthDomains: AUTH_DOMAINS },
  { key: 'chatgpt', name: 'ChatGPT', startUrl: 'https://chatgpt.com/', category: 'Chat', icon: { kind: 'text', value: 'CG' }, trustedFirstPartyDomains: ['chatgpt.com', 'openai.com', 'auth0.com'], trustedAuthDomains: AUTH_DOMAINS },
  { key: 'gemini', name: 'Gemini', startUrl: 'https://gemini.google.com/', category: 'Chat', icon: { kind: 'text', value: 'GE' }, trustedFirstPartyDomains: ['gemini.google.com', 'google.com', 'googleusercontent.com'], trustedAuthDomains: AUTH_DOMAINS },
  { key: 'grok', name: 'Grok', startUrl: 'https://grok.com/', category: 'Chat', icon: { kind: 'text', value: 'GR' }, trustedFirstPartyDomains: ['grok.com', 'x.ai', 'x.com', 'twitter.com'], trustedAuthDomains: AUTH_DOMAINS },
  { key: 'hyperagent', name: 'HyperAgent', startUrl: 'https://hyperagent.com/', category: 'Build', icon: { kind: 'text', value: 'HA' }, trustedFirstPartyDomains: ['hyperagent.com'], trustedAuthDomains: ['auth.hyperagent.com', ...AUTH_DOMAINS] },
  { key: 'perplexity', name: 'Perplexity', startUrl: 'https://www.perplexity.ai/', category: 'Research', icon: { kind: 'text', value: 'PX' }, trustedFirstPartyDomains: ['perplexity.ai'], trustedAuthDomains: AUTH_DOMAINS },
  { key: 'copilot', name: 'Microsoft Copilot', startUrl: 'https://copilot.microsoft.com/', category: 'Chat', icon: { kind: 'text', value: 'MS' }, trustedFirstPartyDomains: ['copilot.microsoft.com', 'microsoft.com'], trustedAuthDomains: AUTH_DOMAINS },
];

export function normalizePlatformUrl(raw: string, allowLocalhost = false): string {
  const input = String(raw || '').trim();
  if (!input) throw new Error('A starting URL is required.');
  let url: URL;
  try { url = new URL(input.includes('://') ? input : `https://${input}`); } catch { throw new Error('Enter a valid HTTPS URL.'); }
  if (FORBIDDEN_PROTOCOLS.has(url.protocol)) throw new Error(`${url.protocol} URLs are not allowed in web platforms.`);
  const localhost = url.hostname === 'localhost' || url.hostname === '127.0.0.1' || url.hostname === '::1';
  if (url.protocol !== 'https:' && !(allowLocalhost && localhost && url.protocol === 'http:')) throw new Error('Web platforms require HTTPS. HTTP is only available for localhost in development mode.');
  if (url.username || url.password) throw new Error('Credentials must not be embedded in platform URLs.');
  if (!url.hostname || url.hostname.endsWith('.local') || url.hostname === '0.0.0.0') throw new Error('Privileged local and internal hosts are not allowed.');
  url.hash = '';
  return url.toString();
}

export function normalizeDomain(raw: string): string {
  const value = String(raw || '').trim().toLowerCase().replace(/^\.+|\.+$/g, '');
  if (!value || value.includes('/') || value.includes(':') || !/^[a-z0-9.-]+$/.test(value)) throw new Error(`Invalid trusted domain: ${raw}`);
  return value;
}

export function hostMatches(host: string, trusted: string): boolean { return host === trusted || host.endsWith(`.${trusted}`); }
export function isTrustedPlatformUrl(platform: WebPlatform, rawUrl: string, allowOnce: ReadonlySet<string> = new Set()): boolean {
  let url: URL;
  try { url = new URL(normalizePlatformUrl(rawUrl, process.env.NODE_ENV === 'development')); } catch { return false; }
  return allowOnce.has(url.hostname) || [...platform.trustedFirstPartyDomains, ...platform.trustedAuthDomains].some((domain) => hostMatches(url.hostname, domain));
}

export function profilePartition(profileId: string): string {
  const safe = profileId.replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 80);
  if (!safe) throw new Error('Invalid browser profile.');
  return `persist:warden-profile-${safe}`;
}

export function platformStorageOrigins(platform: WebPlatform): string[] {
  const origins = new Set<string>();
  for (const candidate of [platform.startUrl, ...platform.trustedFirstPartyDomains.map((domain) => `https://${domain}/`), ...platform.trustedAuthDomains.map((domain) => `https://${domain}/`)]) {
    try { origins.add(new URL(candidate).origin); } catch { /* sanitized definitions should already be valid */ }
  }
  return [...origins].sort();
}

export function createPlatform(input: Partial<WebPlatform> & { name: string; startUrl: string }, profiles: BrowserProfile[], order: number, allowLocalhost = false): WebPlatform {
  const now = new Date().toISOString();
  const startUrl = normalizePlatformUrl(input.startUrl, allowLocalhost);
  const startHost = new URL(startUrl).hostname.toLowerCase();
  const browserProfileId = profiles.some((profile) => profile.id === input.browserProfileId) ? input.browserProfileId! : profiles[0]?.id;
  if (!browserProfileId) throw new Error('Create a browser profile before adding a platform.');
  const cleanDomains = (values: unknown, fallback: string[]): string[] => [...new Set((Array.isArray(values) ? values : fallback).map((value) => normalizeDomain(String(value))))].slice(0, 40);
  const name = String(input.name || '').trim().slice(0, 80);
  if (!name) throw new Error('A display name is required.');
  const icon = input.icon?.kind === 'url'
    ? { kind: 'url' as const, value: normalizePlatformUrl(input.icon.value, allowLocalhost) }
    : { kind: 'text' as const, value: String(input.icon?.value || name.slice(0, 2)).trim().slice(0, 4).toUpperCase() };
  return {
    id: typeof input.id === 'string' && /^platform-[\w-]{1,100}$/.test(input.id) ? input.id : `platform-${randomUUID()}`,
    name, startUrl, category: CATEGORY_VALUES.has(String(input.category)) ? input.category! : 'Other', icon,
    browserProfileId, projectIds: Array.isArray(input.projectIds) ? input.projectIds.filter((id): id is string => typeof id === 'string').slice(0, 100) : [],
    trustedFirstPartyDomains: cleanDomains(input.trustedFirstPartyDomains, [startHost]), trustedAuthDomains: cleanDomains(input.trustedAuthDomains, []),
    enabled: input.enabled !== false, pinned: input.pinned === true, order: Number.isFinite(input.order) ? Number(input.order) : order,
    allowMainView: input.allowMainView !== false, allowSplitView: input.allowSplitView !== false, externalLinks: input.externalLinks === 'system' ? 'system' : 'ask',
    lastUrl: input.lastUrl ? normalizePlatformUrl(input.lastUrl, allowLocalhost) : undefined, createdAt: typeof input.createdAt === 'string' ? input.createdAt : now, updatedAt: now,
  };
}

export function presetInput(key: string): Partial<WebPlatform> & { name: string; startUrl: string } {
  const preset = PLATFORM_PRESETS.find((item) => item.key === key);
  if (!preset) throw new Error('Unknown platform preset.');
  return { ...structuredClone(preset), icon: structuredClone(preset.icon) };
}
