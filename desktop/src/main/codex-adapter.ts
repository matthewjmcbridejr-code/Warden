import { randomUUID } from 'node:crypto';
import type { ApprovalResponse, BuildProvider, NormalizedRunEvent, ProviderAuthReport, ProviderCapabilities, ResumeRunInput, RunApproval, RunEventListener, RunHandle, StartRunInput, Unsubscribe, WardenRun } from '../shared/types';
import { collectEvidence } from './evidence';
import { formatContext } from './context-assembler';
import { CodexRpcClient } from './codex-rpc';
import type { RunStore } from './run-store';

type Listener = (run: WardenRun) => void;
function object(value: unknown): Record<string, unknown> { return value && typeof value === 'object' ? value as Record<string, unknown> : {}; }
function itemFrom(params: Record<string, unknown>): Record<string, unknown> { return object(params.item); }
export function mapCodexNotification(method: string, params: Record<string, unknown>, runId: string): NormalizedRunEvent | null {
  const now = new Date().toISOString(); const item = itemFrom(params); const base = { runId, provider: 'codex', timestamp: now, providerPayload: params };
  if (method === 'item/agentMessage/delta') return { ...base, type: 'message.delta', payload: { delta: String(params.delta || '') } };
  if (method === 'item/started') { if (item.type === 'commandExecution') return { ...base, type: 'command.started', payload: { itemId: item.id, command: item.command, cwd: item.cwd } }; return { ...base, type: 'tool.started', payload: { itemId: item.id, itemType: item.type } }; }
  if (method === 'item/completed') {
    if (item.type === 'commandExecution') return { ...base, type: 'command.completed', payload: { itemId: item.id, command: item.command, cwd: item.cwd, exitCode: item.exitCode, output: item.aggregatedOutput, status: item.status } };
    if (item.type === 'fileChange') return { ...base, type: 'file.changed', payload: { itemId: item.id, changes: item.changes, status: item.status } };
    if (item.type === 'agentMessage') return { ...base, type: 'tool.completed', payload: { itemId: item.id, itemType: item.type, text: item.text } };
    return { ...base, type: 'tool.completed', payload: { itemId: item.id, itemType: item.type, item } };
  }
  if (method === 'turn/completed') { const turn = object(params.turn); const items = Array.isArray(turn.items) ? turn.items.map(object) : []; const final = [...items].reverse().find((candidate) => candidate.type === 'agentMessage'); const status = String(turn.status || 'completed'); return { ...base, type: status === 'completed' ? 'run.completed' : status === 'interrupted' ? 'run.cancelled' : 'run.failed', payload: { turnId: turn.id, status, error: turn.error, finalMessage: final?.text || '' } }; }
  if (method === 'error') return { ...base, type: 'run.failed', payload: { error: params.error || params.message || 'Codex error' } };
  return null;
}
export class CodexAppServerProvider implements BuildProvider {
  readonly id = 'codex'; private rpc = new CodexRpcClient(); private threadRuns = new Map<string, string>(); private runListeners = new Map<string, Set<RunEventListener>>(); private cachedAuth?: { report: ProviderAuthReport; expires: number }; private pendingAuth?: Promise<ProviderAuthReport>;
  constructor(private readonly store: RunStore, private readonly changed: Listener) { this.rpc.onNotification = (method, params) => void this.notification(method, params); this.rpc.onServerRequest = (id, method, params) => this.serverRequest(id, method, params); this.rpc.onStderr = (message) => { if (message.trim()) console.error(`[codex app-server] ${message.trim()}`); }; }
  capabilities(): ProviderCapabilities { return { streaming: true, approvals: true, resume: true, cancellation: true, toolEvents: true, fileChanges: true, usage: false }; }
  async authStatus(): Promise<ProviderAuthReport> {
    if (this.cachedAuth && this.cachedAuth.expires > Date.now()) return this.cachedAuth.report;
    if (this.pendingAuth) return this.pendingAuth;
    this.pendingAuth = this.readAuthStatus().finally(() => { this.pendingAuth = undefined; }); return this.pendingAuth;
  }
  private async readAuthStatus(): Promise<ProviderAuthReport> {
    const checkedAt = new Date().toISOString();
    try {
      await this.rpc.ensureStarted();
      const response = await this.rpc.request<Record<string, unknown>>('account/read', { refreshToken: false });
      const account = object(response.account); const type = String(account.type || '');
      let report: ProviderAuthReport;
      if (type === 'chatgpt') report = { provider: 'codex', state: 'subscription_authenticated', source: 'subscription', installed: true, client: 'codex app-server', entitlement: String(account.planType || 'ChatGPT'), detail: `Codex App Server is authenticated by the official client using ChatGPT (${String(account.planType || 'subscription')}).`, canStart: true, apiFallbackAvailable: false, checkedAt };
      else if (type === 'apiKey') report = { provider: 'codex', state: 'api_key_authenticated', source: 'api_key', installed: true, client: 'codex app-server', detail: 'Codex is currently signed in with an API key. Warden will not start a billed run without explicit approval.', canStart: false, apiFallbackAvailable: true, checkedAt };
      else if (!type) report = { provider: 'codex', state: 'installed_not_authenticated', source: 'none', installed: true, client: 'codex app-server', detail: 'Codex is installed but not authenticated. Run `codex login` and choose Sign in with ChatGPT.', canStart: false, apiFallbackAvailable: false, checkedAt };
      else report = { provider: 'codex', state: 'unsupported', source: 'unknown', installed: true, client: 'codex app-server', detail: `Codex reports unsupported authentication type ${type}.`, canStart: false, apiFallbackAvailable: false, checkedAt };
      this.cachedAuth = { report, expires: Date.now() + 5 * 60_000 }; return report;
    } catch (error) { return { provider: 'codex', state: 'disconnected', source: 'none', installed: false, client: 'codex app-server', detail: `Codex App Server is unavailable: ${error instanceof Error ? error.message : String(error)}`, canStart: false, apiFallbackAvailable: false, checkedAt }; }
  }
  private publish(run: WardenRun, event?: NormalizedRunEvent): void { this.changed(run); if (event) for (const listener of this.runListeners.get(run.id) || []) listener(event); }
  async startRun(input: StartRunInput): Promise<RunHandle> {
    const auth = await this.authStatus();
    if (input.authSource === 'subscription' && auth.state !== 'subscription_authenticated') throw new Error(`Codex subscription run unavailable: ${auth.detail}`);
    if (input.authSource === 'api_key' && (auth.state !== 'api_key_authenticated' || !input.apiFallbackApproved)) throw new Error('Codex API-key execution requires the official client to be API-key authenticated and explicit billing approval.');
    const activeAuth = input.authSource === 'api_key' ? { ...auth, canStart: true, detail: 'Codex API-key authentication explicitly approved for this run.' } : auth;
    const run = this.store.create({ provider: this.id, project: input.project, projectId: input.projectId, cwd: input.workingDirectory, prompt: input.prompt, model: input.model, context: input.context, auth: activeAuth }); this.publish(run);
    try {
      await this.rpc.ensureStarted();
      const response = await this.rpc.request<Record<string, unknown>>('thread/start', { cwd: input.workingDirectory, model: input.model || null, approvalPolicy: 'untrusted', sandbox: 'workspace-write', ephemeral: false });
      const thread = object(response.thread); const threadId = String(thread.id || ''); if (!threadId) throw new Error('Codex did not return a thread ID.');
      this.threadRuns.set(threadId, run.id); const prompt = input.context ? `${formatContext(input.context)}\n\n<user-task>\n${input.prompt}\n</user-task>` : input.prompt;
      const turnResponse = await this.rpc.request<Record<string, unknown>>('turn/start', { threadId, cwd: input.workingDirectory, approvalPolicy: 'untrusted', input: [{ type: 'text', text: prompt, text_elements: [] }] }); const turn = object(turnResponse.turn);
      const updated = this.store.update(run.id, { threadId, turnId: String(turn.id || ''), status: 'running' }); this.publish(updated); return { runId: run.id, threadId, provider: this.id };
    } catch (error) { const failed = this.store.update(run.id, { status: 'failed', error: error instanceof Error ? error.message : String(error) }); this.publish(failed); throw error; }
  }
  async resumeRun(input: ResumeRunInput): Promise<RunHandle> { const run = this.store.get(input.runId); if (!run?.threadId) throw new Error('Run has no resumable Codex thread.'); if (run.auth?.source === 'api_key') throw new Error('API-key runs require a fresh explicit billing approval; start a new run instead of resuming silently.'); const auth = await this.authStatus(); if (auth.state !== 'subscription_authenticated') throw new Error(`Codex subscription resume unavailable: ${auth.detail}`); await this.rpc.ensureStarted(); await this.rpc.request('thread/resume', { threadId: run.threadId, cwd: run.cwd, approvalPolicy: 'untrusted', sandbox: 'workspace-write' }); this.threadRuns.set(run.threadId, run.id); let turnId = run.turnId; if (input.prompt?.trim()) { const response = await this.rpc.request<Record<string, unknown>>('turn/start', { threadId: run.threadId, cwd: run.cwd, approvalPolicy: 'untrusted', input: [{ type: 'text', text: input.prompt.trim(), text_elements: [] }] }); turnId = String(object(response.turn).id || ''); } const updated = this.store.update(run.id, { auth, turnId, status: 'running', error: undefined }); this.publish(updated); return { runId: run.id, threadId: run.threadId, provider: this.id }; }
  async cancelRun(runId: string): Promise<void> { const run = this.store.get(runId); if (!run?.threadId || !run.turnId) throw new Error('Run is not active.'); await this.rpc.ensureStarted(); await this.rpc.request('turn/interrupt', { threadId: run.threadId, turnId: run.turnId }); const updated = this.store.update(runId, { status: 'cancelled' }); this.publish(updated); }
  async respondToApproval(input: ApprovalResponse): Promise<void> { const run = this.store.get(input.runId); const approval = run?.approvals.find((item) => item.id === input.approvalId && item.status === 'pending'); if (!run || !approval) throw new Error('Pending approval not found.'); if (approval.method === 'item/permissions/requestApproval') { const raw = object(approval.providerPayload); this.rpc.respond(approval.requestId, { permissions: input.decision === 'approve' ? object(raw.permissions) : {}, scope: input.scope === 'session' ? 'session' : 'turn' }); } else { const decision = input.decision === 'deny' ? 'decline' : input.scope === 'session' ? 'acceptForSession' : 'accept'; this.rpc.respond(approval.requestId, { decision }); } const updated = this.store.resolveApproval(run.id, approval.id, input.decision === 'approve' ? 'approved' : 'denied'); this.publish(updated); }
  subscribe(runId: string, listener: RunEventListener): Unsubscribe { const listeners = this.runListeners.get(runId) || new Set(); listeners.add(listener); this.runListeners.set(runId, listeners); return () => listeners.delete(listener); }
  private async notification(method: string, params: Record<string, unknown>): Promise<void> { const threadId = String(params.threadId || ''); const runId = this.threadRuns.get(threadId); if (!runId) return; const event = mapCodexNotification(method, params, runId); if (!event) return; let run = this.store.appendEvent(runId, event); if (event.type === 'run.completed' || event.type === 'run.failed' || event.type === 'run.cancelled') { const status = event.type === 'run.completed' ? 'completed' : event.type === 'run.cancelled' ? 'interrupted' : 'failed'; run = this.store.update(runId, { status, error: event.type === 'run.failed' ? String(event.payload.error || 'Codex run failed.') : undefined }); run = this.store.update(runId, { evidence: await collectEvidence(run) }); } this.publish(run, event); }
  private serverRequest(requestId: string | number, method: string, params: Record<string, unknown>): void { if (!['item/commandExecution/requestApproval', 'item/fileChange/requestApproval', 'item/permissions/requestApproval'].includes(method)) { this.rpc.respondError(requestId, `Warden AI Desk does not yet implement ${method}.`); return; } const threadId = String(params.threadId || ''); const runId = this.threadRuns.get(threadId); if (!runId) { if (method === 'item/permissions/requestApproval') this.rpc.respond(requestId, { permissions: {}, scope: 'turn' }); else this.rpc.respond(requestId, { decision: 'decline' }); return; } const command = String(params.command || ''); const detail = command || String(params.reason || params.grantRoot || 'Codex requests permission.'); const approval: RunApproval = { id: `approval-${randomUUID()}`, requestId, method, status: 'pending', title: method.includes('fileChange') ? 'Approve file changes' : method.includes('commandExecution') ? 'Approve command' : 'Approve permission', detail, createdAt: new Date().toISOString(), providerPayload: params }; let run = this.store.addApproval(runId, approval); const event: NormalizedRunEvent = { type: 'approval.requested', runId, provider: 'codex', timestamp: approval.createdAt, payload: { approvalId: approval.id, method, title: approval.title, detail }, providerPayload: params }; run = this.store.appendEvent(runId, event); this.publish(run, event); }
  shutdown(): void { this.rpc.shutdown(); }
}
