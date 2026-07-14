import { spawn } from 'node:child_process';
import { access } from 'node:fs/promises';
import { delimiter, join } from 'node:path';
import { createInterface } from 'node:readline';
import type { ProviderAuthReport, StructuredProviderId } from '../shared/types';

type ProbeResult = { code: number | null; stdout: string; stderr: string; timedOut: boolean };

const API_ENV: Record<StructuredProviderId, string[]> = {
  codex: ['OPENAI_API_KEY', 'CODEX_API_KEY'],
  claude: ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'],
  gemini: ['GEMINI_API_KEY', 'GOOGLE_API_KEY'],
  grok: ['XAI_API_KEY'],
};
const SUBSCRIPTION_OVERRIDE_ENV: Partial<Record<StructuredProviderId, string[]>> = {
  codex: ['CODEX_ACCESS_TOKEN'],
  claude: ['CLAUDE_CODE_OAUTH_TOKEN'],
  gemini: ['GOOGLE_GENAI_USE_VERTEXAI', 'GOOGLE_APPLICATION_CREDENTIALS'],
};

export function clientEnvironment(provider: StructuredProviderId, source: 'subscription' | 'api_key'): NodeJS.ProcessEnv {
  const env = { ...process.env };
  // Empty (rather than delete) prevents clients such as Gemini CLI from
  // re-populating a billable key from a project-level .env file.
  if (source === 'subscription') for (const key of [...API_ENV[provider], ...(SUBSCRIPTION_OVERRIDE_ENV[provider] || [])]) env[key] = '';
  if (provider === 'gemini') env.GEMINI_DEFAULT_AUTH_TYPE = source === 'subscription' ? 'oauth-personal' : 'gemini-api-key';
  return env;
}

export function apiFallbackAvailable(provider: StructuredProviderId): boolean {
  return API_ENV[provider].some((key) => Boolean(process.env[key]));
}

export async function findClient(command: string): Promise<string | null> {
  for (const directory of (process.env.PATH || '').split(delimiter)) {
    if (!directory) continue;
    const candidate = join(directory, command);
    try { await access(candidate); return candidate; } catch { /* continue */ }
  }
  return null;
}

export function runProbe(command: string, args: string[], options: { env?: NodeJS.ProcessEnv; cwd?: string; timeoutMs?: number } = {}): Promise<ProbeResult> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd: options.cwd, env: options.env || process.env, shell: false, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = ''; let stderr = ''; let settled = false;
    const finish = (code: number | null, timedOut = false): void => { if (settled) return; settled = true; clearTimeout(timer); resolve({ code, stdout: stdout.slice(-64_000), stderr: stderr.slice(-64_000), timedOut }); };
    child.stdout.on('data', (data) => { stdout += String(data); if (stdout.length > 128_000) stdout = stdout.slice(-64_000); });
    child.stderr.on('data', (data) => { stderr += String(data); if (stderr.length > 128_000) stderr = stderr.slice(-64_000); });
    child.once('error', (error) => { stderr += error.message; finish(null); });
    child.once('close', (code) => finish(code));
    const timer = setTimeout(() => { child.kill('SIGTERM'); finish(null, true); }, options.timeoutMs || 8_000);
  });
}

async function acpAuthProbe(command: string, args: string[], methodId: string, env: NodeJS.ProcessEnv): Promise<{ ok: boolean; methods: string[]; error?: string }> {
  const child = spawn(command, args, { env, shell: false, stdio: ['pipe', 'pipe', 'pipe'] }); const lines = createInterface({ input: child.stdout }); let nextId = 1; let stderr = '';
  const pending = new Map<number, { resolve(value: Record<string, unknown>): void; reject(error: Error): void }>();
  child.stderr.on('data', (data) => { stderr = `${stderr}${String(data)}`.slice(-12_000); });
  lines.on('line', (line) => { let message: Record<string, unknown>; try { message = JSON.parse(line) as Record<string, unknown>; } catch { return; } if (typeof message.id !== 'number') return; const request = pending.get(message.id); if (!request) return; pending.delete(message.id); const error = message.error as Record<string, unknown> | undefined; if (error) request.reject(new Error(String(error.message || 'ACP request failed.'))); else request.resolve(object(message.result)); });
  const request = (method: string, params: Record<string, unknown>): Promise<Record<string, unknown>> => { const id = nextId++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`); }); };
  const timed = <T>(promise: Promise<T>): Promise<T> => new Promise((resolve, reject) => { const timer = setTimeout(() => reject(new Error('ACP authentication probe timed out.')), 15_000); promise.then((value) => { clearTimeout(timer); resolve(value); }, (error) => { clearTimeout(timer); reject(error); }); });
  try {
    const init = await timed(request('initialize', { protocolVersion: 1, clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false } }));
    const methods = Array.isArray(init.authMethods) ? init.authMethods.map((value) => String(object(value).id || '')).filter(Boolean) : [];
    if (!methods.includes(methodId)) return { ok: false, methods, error: `Official client did not advertise ${methodId} authentication.` };
    await timed(request('authenticate', { methodId, _meta: { headless: true } })); return { ok: true, methods };
  } catch (error) { return { ok: false, methods: [], error: `${error instanceof Error ? error.message : String(error)}${stderr.trim() ? `: ${stderr.trim().slice(-600)}` : ''}` }; }
  finally { lines.close(); child.kill('SIGTERM'); }
}

function object(value: unknown): Record<string, unknown> { return value && typeof value === 'object' ? value as Record<string, unknown> : {}; }

function report(provider: StructuredProviderId, input: Partial<ProviderAuthReport> & Pick<ProviderAuthReport, 'state' | 'source' | 'detail'>): ProviderAuthReport {
  return { provider, installed: true, client: provider === 'codex' ? 'codex app-server' : provider === 'claude' ? 'claude' : provider === 'gemini' ? 'gemini' : 'grok', canStart: input.state === 'subscription_authenticated' || input.state === 'api_key_authenticated', apiFallbackAvailable: apiFallbackAvailable(provider), checkedAt: new Date().toISOString(), ...input };
}

export async function cliAuthStatus(provider: Exclude<StructuredProviderId, 'codex'>): Promise<ProviderAuthReport> {
  const command = provider === 'claude' ? 'claude' : provider;
  if (!await findClient(command)) return report(provider, { installed: false, state: 'disconnected', source: 'none', detail: `Official ${command} client is not installed or is not on PATH.`, canStart: false });
  const versionResult = await runProbe(command, ['--version']);
  const version = (versionResult.stdout || versionResult.stderr).trim().split('\n')[0].slice(0, 160) || undefined;
  if (provider === 'claude') {
    const result = await runProbe('claude', ['auth', 'status', '--json'], { env: clientEnvironment('claude', 'subscription') });
    try {
      const status = JSON.parse(result.stdout) as Record<string, unknown>;
      if (status.loggedIn === true && status.authMethod === 'claude.ai') return report(provider, { version, state: 'subscription_authenticated', source: 'subscription', entitlement: String(status.subscriptionType || 'unknown'), detail: `Claude Code is signed in with Claude.ai (${String(status.subscriptionType || 'subscription')} plan). API credentials are excluded from subscription runs.` });
      if (status.loggedIn === true) return report(provider, { version, state: 'api_key_authenticated', source: 'api_key', detail: `Claude Code reports ${String(status.authMethod || 'non-subscription')} authentication. API billing requires explicit approval.`, canStart: false });
      return report(provider, { version, state: 'installed_not_authenticated', source: 'none', detail: 'Claude Code is installed but not signed in. Run `claude` and complete the official login flow.', canStart: false });
    } catch { return report(provider, { version, state: 'installed_not_authenticated', source: 'none', detail: `Claude Code could not report authentication status${result.stderr ? `: ${result.stderr.trim().slice(0, 300)}` : '.'}`, canStart: false }); }
  }
  if (provider === 'gemini') {
    const probe = await acpAuthProbe('gemini', ['--acp'], 'oauth-personal', clientEnvironment('gemini', 'subscription')); const output = probe.error || '';
    if (probe.ok) return report(provider, { version, state: 'subscription_authenticated', source: 'subscription', entitlement: 'Google account / Gemini Code Assist', detail: 'Gemini CLI authenticated its ACP client using the locally cached Google-account login.' });
    if (/IneligibleTierError|ineligible|unsupported for Gemini Code Assist/i.test(output)) return report(provider, { version, state: 'unknown_entitlement', source: 'subscription', entitlement: 'Google account detected; client rejected current tier', detail: 'Gemini CLI reached Google authentication but rejected this account/client entitlement. Update or re-authenticate the official client; Warden will not switch to API billing.', canStart: false });
    if (/auth|login|credential/i.test(output)) return report(provider, { version, state: 'installed_not_authenticated', source: 'none', detail: 'Gemini CLI is installed but its Google-account login could not be validated. Run `gemini` to authenticate.', canStart: false });
    return report(provider, { version, state: 'unknown_entitlement', source: 'unknown', detail: `Gemini CLI entitlement probe failed without exposing credentials: ${output.trim().slice(-300) || 'unknown error'}`, canStart: false });
  }
  const probe = await acpAuthProbe('grok', ['--no-auto-update', 'agent', 'stdio'], 'cached_token', clientEnvironment('grok', 'subscription')); const output = probe.error || '';
  if (probe.ok) return report(provider, { version, state: 'subscription_authenticated', source: 'subscription', entitlement: 'Grok cached login', detail: 'Grok Build authenticated its ACP client using the locally cached login with XAI_API_KEY excluded.' });
  if (/login|sign in|auth|credential/i.test(output)) return report(provider, { version, state: 'installed_not_authenticated', source: 'none', detail: 'Grok Build is installed but not authenticated. Run `grok login`.', canStart: false });
  return report(provider, { version, state: 'unknown_entitlement', source: 'unknown', detail: `Grok Build entitlement probe failed: ${output.trim().slice(-300) || 'unknown error'}`, canStart: false });
}

export function enforceAuthChoice(reportValue: ProviderAuthReport, source: 'subscription' | 'api_key', approved?: boolean): void {
  if (source === 'subscription') {
    if (reportValue.state !== 'subscription_authenticated') throw new Error(`${reportValue.provider} cannot start with subscription billing: ${reportValue.detail}`);
    return;
  }
  if (!reportValue.apiFallbackAvailable) throw new Error(`${reportValue.provider} API fallback is not configured in the launch environment.`);
  if (!approved) throw new Error('API-key execution requires explicit billing approval for this run.');
}
