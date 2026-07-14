import { randomUUID } from 'node:crypto';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import type { ApprovalResponse, BuildProvider, NormalizedRunEvent, ProviderAuthReport, ProviderCapabilities, ResumeRunInput, RunEventListener, RunHandle, StartRunInput, StructuredProviderId, Unsubscribe, WardenRun } from '../shared/types';
import { formatContext } from './context-assembler';
import { collectEvidence } from './evidence';
import { clientEnvironment, cliAuthStatus, enforceAuthChoice } from './provider-auth';
import type { RunStore } from './run-store';

type CliProviderId = Exclude<StructuredProviderId, 'codex'>;
type Listener = (run: WardenRun) => void;
type ActiveProcess = { child: ChildProcessWithoutNullStreams; stderr: string };

function object(value: unknown): Record<string, unknown> { return value && typeof value === 'object' ? value as Record<string, unknown> : {}; }
function textParts(value: unknown): string { if (!Array.isArray(value)) return ''; return value.map((part) => { const item = object(part); return item.type === 'text' ? String(item.text || '') : ''; }).join(''); }

export function mapCliEvent(provider: CliProviderId, raw: Record<string, unknown>, runId: string): NormalizedRunEvent | null {
  const base = { runId, provider, timestamp: new Date().toISOString(), providerPayload: raw };
  const type = String(raw.type || '');
  if (provider === 'claude') {
    if (type === 'assistant') { const message = object(raw.message); const text = textParts(message.content); return text ? { ...base, type: 'message.delta', payload: { delta: text } } : null; }
    if (type === 'result') return { ...base, type: raw.is_error ? 'run.failed' : 'run.completed', payload: { finalMessage: String(raw.result || ''), error: raw.is_error ? String(raw.result || 'Claude run failed.') : undefined, sessionId: raw.session_id, usage: raw.usage } };
    return null;
  }
  if (provider === 'grok') {
    if (type === 'text') return { ...base, type: 'message.delta', payload: { delta: String(raw.data || '') } };
    if (type === 'tool_use' || type === 'tool-start') return { ...base, type: 'tool.started', payload: { name: raw.name, input: raw.input || raw.data } };
    if (type === 'tool_result' || type === 'tool-end') return { ...base, type: 'tool.completed', payload: { name: raw.name, output: raw.output || raw.data } };
    if (type === 'end') return { ...base, type: 'run.completed', payload: { finalMessage: '', stopReason: raw.stopReason, sessionId: raw.sessionId } };
    if (type === 'error') return { ...base, type: 'run.failed', payload: { error: String(raw.error || raw.message || raw.data || 'Grok run failed.') } };
    return null;
  }
  if (type === 'message') return { ...base, type: 'message.delta', payload: { delta: String(raw.content || raw.text || raw.message || '') } };
  if (type === 'tool_use' || type === 'tool_call') return { ...base, type: 'tool.started', payload: { name: raw.tool_name || raw.name, input: raw.parameters || raw.input } };
  if (type === 'tool_result') return { ...base, type: 'tool.completed', payload: { name: raw.tool_name || raw.name, output: raw.output || raw.result } };
  if (type === 'result') return { ...base, type: raw.error ? 'run.failed' : 'run.completed', payload: { finalMessage: String(raw.response || raw.result || ''), error: raw.error, stats: raw.stats, sessionId: raw.session_id } };
  if (type === 'error') return { ...base, type: 'run.failed', payload: { error: String(raw.message || raw.error || 'Gemini run failed.') } };
  return null;
}

export class StructuredCliProvider implements BuildProvider {
  readonly id: CliProviderId;
  private active = new Map<string, ActiveProcess>();
  private runListeners = new Map<string, Set<RunEventListener>>();
  private cachedAuth?: { report: ProviderAuthReport; expires: number };
  private pendingAuth?: Promise<ProviderAuthReport>;

  constructor(id: CliProviderId, private readonly store: RunStore, private readonly changed: Listener) { this.id = id; }
  capabilities(): ProviderCapabilities { return { streaming: true, approvals: false, resume: true, cancellation: true, toolEvents: true, fileChanges: false, usage: this.id !== 'grok' }; }
  async authStatus(): Promise<ProviderAuthReport> { if (this.cachedAuth && this.cachedAuth.expires > Date.now()) return this.cachedAuth.report; if (this.pendingAuth) return this.pendingAuth; this.pendingAuth = cliAuthStatus(this.id).then((value) => { this.cachedAuth = { report: value, expires: Date.now() + 5 * 60_000 }; return value; }).finally(() => { this.pendingAuth = undefined; }); return this.pendingAuth; }
  private publish(run: WardenRun, event?: NormalizedRunEvent): void { this.changed(run); if (event) for (const listener of this.runListeners.get(run.id) || []) listener(event); }
  private authSnapshot(report: ProviderAuthReport, source: 'subscription' | 'api_key'): ProviderAuthReport { return source === 'subscription' ? report : { ...report, state: 'api_key_authenticated', source: 'api_key', canStart: true, detail: `${this.id} API-key fallback explicitly approved for this run. Usage may be billed by the provider.`, checkedAt: new Date().toISOString() }; }
  async startRun(input: StartRunInput): Promise<RunHandle> {
    const report = await this.authStatus(); enforceAuthChoice(report, input.authSource, input.apiFallbackApproved);
    const auth = this.authSnapshot(report, input.authSource); const sessionId = randomUUID();
    let run = this.store.create({ provider: this.id, project: input.project, projectId: input.projectId, cwd: input.workingDirectory, prompt: input.prompt, model: input.model, context: input.context, auth });
    run = this.store.update(run.id, { threadId: sessionId, status: 'running' });
    const started: NormalizedRunEvent = { type: 'run.started', runId: run.id, provider: this.id, timestamp: new Date().toISOString(), payload: { sessionId, authSource: auth.source, client: auth.client } };
    run = this.store.appendEvent(run.id, started); this.publish(run, started);
    try { await this.launch(run, input.context ? `${formatContext(input.context)}\n\n<user-task>\n${input.prompt}\n</user-task>` : input.prompt, input.authSource, false); return { runId: run.id, threadId: sessionId, provider: this.id }; }
    catch (error) { const failed = this.store.update(run.id, { status: 'failed', error: error instanceof Error ? error.message : String(error) }); this.publish(failed); throw error; }
  }
  async resumeRun(input: ResumeRunInput): Promise<RunHandle> {
    const run = this.store.get(input.runId); if (!run?.threadId) throw new Error(`Run has no resumable ${this.id} session.`); if (!input.prompt?.trim()) throw new Error('Enter a prompt to resume this run.');
    const source = run.auth?.source === 'api_key' ? 'api_key' : 'subscription';
    if (source === 'api_key') throw new Error('API-key runs require a fresh explicit billing approval; start a new run instead of resuming silently.');
    const report = await this.authStatus(); enforceAuthChoice(report, 'subscription');
    const updated = this.store.update(run.id, { auth: report, status: 'running', error: undefined }); this.publish(updated);
    try { await this.launch(updated, input.prompt.trim(), 'subscription', true); return { runId: run.id, threadId: run.threadId, provider: this.id }; }
    catch (error) { const failed = this.store.update(run.id, { status: 'failed', error: error instanceof Error ? error.message : String(error) }); this.publish(failed); throw error; }
  }
  private args(run: WardenRun, prompt: string, resume: boolean): string[] {
    const model = run.model ? ['--model', run.model] : [];
    if (this.id === 'claude') return ['-p', prompt, '--output-format', 'stream-json', '--verbose', '--permission-mode', 'default', ...(resume ? ['--resume', run.threadId!] : ['--session-id', run.threadId!]), ...model];
    if (this.id === 'gemini') return ['-p', prompt, '--output-format', 'stream-json', '--approval-mode', 'default', ...(resume ? ['--resume', run.threadId!] : ['--session-id', run.threadId!]), ...model];
    return ['--no-auto-update', '-p', prompt, '--output-format', 'streaming-json', '--permission-mode', 'default', '--cwd', run.cwd, ...(resume ? ['--resume', run.threadId!] : ['--session-id', run.threadId!]), '--no-subagents', ...model];
  }
  private async launch(run: WardenRun, prompt: string, source: 'subscription' | 'api_key', resume: boolean): Promise<void> {
    if (this.active.has(run.id)) throw new Error('Run is already active.');
    const child = spawn(this.id, this.args(run, prompt, resume), { cwd: run.cwd, env: clientEnvironment(this.id, source), shell: false, stdio: ['pipe', 'pipe', 'pipe'] });
    const active = { child, stderr: '' }; this.active.set(run.id, active);
    child.stderr.on('data', (data) => { active.stderr = `${active.stderr}${String(data)}`.slice(-12_000); });
    createInterface({ input: child.stdout }).on('line', (line) => { let raw: Record<string, unknown>; try { raw = JSON.parse(line) as Record<string, unknown>; } catch { return; } const event = mapCliEvent(this.id, raw, run.id); if (event) void this.acceptEvent(run.id, event); });
    child.once('close', (code, signal) => { this.active.delete(run.id); void this.finish(run.id, code, signal, active.stderr); });
    await new Promise<void>((resolve, reject) => { child.once('spawn', resolve); child.once('error', reject); });
  }
  private async acceptEvent(runId: string, event: NormalizedRunEvent): Promise<void> {
    let run = this.store.appendEvent(runId, event);
    if (event.type === 'message.delta') run = this.store.update(runId, { evidence: { ...run.evidence, finalMessage: `${run.evidence.finalMessage || ''}${String(event.payload.delta || '')}`.slice(-100_000) } });
    if (event.type === 'run.completed' || event.type === 'run.failed') { const finalMessage = String(event.payload.finalMessage || ''); run = this.store.update(runId, { status: event.type === 'run.completed' ? 'completed' : 'failed', error: event.type === 'run.failed' ? String(event.payload.error || 'Provider run failed.') : undefined, evidence: { ...run.evidence, finalMessage: finalMessage || run.evidence.finalMessage } }); }
    this.publish(run, event);
  }
  private async finish(runId: string, code: number | null, signal: NodeJS.Signals | null, stderr: string): Promise<void> {
    let run = this.store.get(runId); if (!run) return;
    if (!['completed', 'failed', 'cancelled', 'interrupted'].includes(run.status)) {
      const success = code === 0; const event: NormalizedRunEvent = { type: success ? 'run.completed' : 'run.failed', runId, provider: this.id, timestamp: new Date().toISOString(), payload: success ? { finalMessage: run.evidence.finalMessage || '' } : { error: stderr.trim().slice(-3000) || `${this.id} exited (${code ?? signal ?? 'unknown'}).` } };
      await this.acceptEvent(runId, event); run = this.store.get(runId)!;
    }
    run = this.store.update(runId, { evidence: await collectEvidence(run) }); this.publish(run);
  }
  async cancelRun(runId: string): Promise<void> { const active = this.active.get(runId); if (!active) throw new Error('Run is not active.'); active.child.kill('SIGTERM'); const event: NormalizedRunEvent = { type: 'run.cancelled', runId, provider: this.id, timestamp: new Date().toISOString(), payload: {} }; let run = this.store.appendEvent(runId, event); run = this.store.update(runId, { status: 'cancelled' }); this.publish(run, event); }
  async respondToApproval(_input: ApprovalResponse): Promise<void> { throw new Error(`${this.id} headless adapter does not expose an external approval callback. Unapproved tools remain denied by the official client.`); }
  subscribe(runId: string, listener: RunEventListener): Unsubscribe { const listeners = this.runListeners.get(runId) || new Set(); listeners.add(listener); this.runListeners.set(runId, listeners); return () => listeners.delete(listener); }
  shutdown(): void { for (const [runId, active] of this.active) { const run = this.store.get(runId); if (run && ['starting', 'running', 'waiting_approval'].includes(run.status)) this.store.update(runId, { status: 'interrupted', error: 'Warden AI Desk closed while this provider run was active. The official client session is preserved for resume.' }); active.child.kill('SIGTERM'); } this.active.clear(); }
}
