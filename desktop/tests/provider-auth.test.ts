import { afterEach, describe, expect, it } from 'vitest';
import type { ProviderAuthReport } from '../src/shared/types';
import { apiFallbackAvailable, clientEnvironment, enforceAuthChoice } from '../src/main/provider-auth';

const original = { ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY, GEMINI_API_KEY: process.env.GEMINI_API_KEY, XAI_API_KEY: process.env.XAI_API_KEY };
afterEach(() => { for (const [key, value] of Object.entries(original)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; } });

function report(overrides: Partial<ProviderAuthReport> = {}): ProviderAuthReport { return { provider: 'claude', state: 'subscription_authenticated', source: 'subscription', installed: true, client: 'claude', detail: 'Pro subscription', canStart: true, apiFallbackAvailable: false, checkedAt: new Date().toISOString(), ...overrides }; }

describe('subscription-first authentication', () => {
  it('removes API credentials from subscription child environments', () => { process.env.ANTHROPIC_API_KEY = 'must-not-pass'; const env = clientEnvironment('claude', 'subscription'); expect(env.ANTHROPIC_API_KEY).toBe(''); expect(process.env.ANTHROPIC_API_KEY).toBe('must-not-pass'); });
  it('forces Gemini Google-account auth for subscription runs', () => { process.env.GEMINI_API_KEY = 'must-not-pass'; const env = clientEnvironment('gemini', 'subscription'); expect(env.GEMINI_API_KEY).toBe(''); expect(env.GEMINI_DEFAULT_AUTH_TYPE).toBe('oauth-personal'); });
  it('does not misclassify an OAuth login token as API billing', () => { const previous = process.env.CLAUDE_CODE_OAUTH_TOKEN; process.env.CLAUDE_CODE_OAUTH_TOKEN = 'oauth-owned-by-client'; delete process.env.ANTHROPIC_API_KEY; delete process.env.ANTHROPIC_AUTH_TOKEN; expect(apiFallbackAvailable('claude')).toBe(false); const env = clientEnvironment('claude', 'subscription'); expect(env.CLAUDE_CODE_OAUTH_TOKEN).toBe(''); if (previous === undefined) delete process.env.CLAUDE_CODE_OAUTH_TOKEN; else process.env.CLAUDE_CODE_OAUTH_TOKEN = previous; });
  it('never allows API fallback without an explicit per-run approval', () => { const value = report({ apiFallbackAvailable: true }); expect(() => enforceAuthChoice(value, 'api_key', false)).toThrow('explicit billing approval'); expect(() => enforceAuthChoice(value, 'api_key', true)).not.toThrow(); });
  it('refuses a subscription run when entitlement is unknown', () => { expect(() => enforceAuthChoice(report({ state: 'unknown_entitlement', canStart: false }), 'subscription')).toThrow('cannot start with subscription billing'); });
});
