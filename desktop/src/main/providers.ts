import type { ProviderDefinition, ProviderId } from '../shared/types';

export const PROVIDERS: Record<ProviderId, ProviderDefinition> = {
  claude: { id: 'claude', name: 'Claude', homeUrl: 'https://claude.ai/', partition: 'persist:warden-claude' },
  chatgpt: { id: 'chatgpt', name: 'ChatGPT', homeUrl: 'https://chatgpt.com/', partition: 'persist:warden-chatgpt' },
  gemini: { id: 'gemini', name: 'Gemini', homeUrl: 'https://gemini.google.com/', partition: 'persist:warden-gemini' },
  grok: { id: 'grok', name: 'Grok', homeUrl: 'https://grok.com/', partition: 'persist:warden-grok' },
};

const PROVIDER_HOSTS: Record<ProviderId, string[]> = {
  claude: ['claude.ai', 'anthropic.com'],
  chatgpt: ['chatgpt.com', 'openai.com', 'auth0.com'],
  gemini: ['gemini.google.com', 'google.com', 'googleusercontent.com'],
  grok: ['grok.com', 'x.ai', 'x.com', 'twitter.com'],
};
const AUTH_HOSTS = ['accounts.google.com', 'appleid.apple.com', 'login.microsoftonline.com', 'github.com'];

function hostMatches(host: string, allowed: string): boolean { return host === allowed || host.endsWith(`.${allowed}`); }
export function isAllowedProviderUrl(provider: ProviderId, rawUrl: string): boolean {
  try {
    const url = new URL(rawUrl);
    if (url.protocol !== 'https:') return false;
    return [...PROVIDER_HOSTS[provider], ...AUTH_HOSTS].some((host) => hostMatches(url.hostname, host));
  } catch { return false; }
}
