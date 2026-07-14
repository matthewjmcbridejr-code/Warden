import { describe, expect, it } from 'vitest';
import { isAllowedProviderUrl, PROVIDERS } from '../src/main/providers';

describe('provider security policy', () => {
  it('uses isolated persistent partitions', () => {
    const partitions = Object.values(PROVIDERS).map((provider) => provider.partition);
    expect(new Set(partitions).size).toBe(4);
    expect(partitions.every((partition) => partition.startsWith('persist:warden-'))).toBe(true);
  });
  it('keeps expected provider and OAuth hosts inside the provider session', () => {
    expect(isAllowedProviderUrl('chatgpt', 'https://auth.openai.com/authorize')).toBe(true);
    expect(isAllowedProviderUrl('claude', 'https://accounts.google.com/o/oauth2/auth')).toBe(true);
    expect(isAllowedProviderUrl('gemini', 'https://gemini.google.com/app')).toBe(true);
    expect(isAllowedProviderUrl('grok', 'https://x.com/i/flow/login')).toBe(true);
  });
  it('rejects external, insecure, and malformed navigation', () => {
    expect(isAllowedProviderUrl('chatgpt', 'https://example.com/')).toBe(false);
    expect(isAllowedProviderUrl('claude', 'http://claude.ai/')).toBe(false);
    expect(isAllowedProviderUrl('gemini', 'not a url')).toBe(false);
  });
});
