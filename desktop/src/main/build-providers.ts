import type { ApprovalResponse, BuildProvider, ProviderAuthReport, ProviderCapabilities, ResumeRunInput, RunEventListener, RunHandle, StartRunInput, StructuredProviderId, Unsubscribe } from '../shared/types';

export class DisconnectedBuildProvider implements BuildProvider {
  constructor(public readonly id: string, public readonly reason: string) {}
  capabilities(): ProviderCapabilities { return { streaming: false, approvals: false, resume: false, cancellation: false, toolEvents: false, fileChanges: false, usage: false }; }
  async authStatus(): Promise<ProviderAuthReport> { return { provider: this.id as StructuredProviderId, state: 'unsupported', source: 'none', installed: false, client: this.id, detail: this.reason, canStart: false, apiFallbackAvailable: false, checkedAt: new Date().toISOString() }; }
  private unavailable(): never { throw new Error(`${this.id} structured adapter not connected: ${this.reason}`); }
  async startRun(_input: StartRunInput): Promise<RunHandle> { return this.unavailable(); }
  async resumeRun(_input: ResumeRunInput): Promise<RunHandle> { return this.unavailable(); }
  async cancelRun(_runId: string): Promise<void> { this.unavailable(); }
  async respondToApproval(_input: ApprovalResponse): Promise<void> { this.unavailable(); }
  subscribe(_runId: string, _listener: RunEventListener): Unsubscribe { return () => undefined; }
}

// Boundary only: the implementation must speak Codex App Server JSON-RPC over
// stdio (initialize, thread/start|resume, turn/start, notifications, approvals).
// It must never delegate to Warden's legacy tmux prompt-injection runner.
export class CodexAppServerAdapter extends DisconnectedBuildProvider {
  constructor() { super('codex', 'App Server transport and approval bridge are the next implementation slice'); }
}
