export const providerIds = ['claude', 'chatgpt', 'gemini', 'grok'] as const;
export type ProviderId = typeof providerIds[number];
export type WorkspaceId = 'chat' | 'build';
export type ExecutionMode = 'local' | 'codex' | 'claude' | 'gemini' | 'grok';

export interface ProviderDefinition { id: ProviderId; name: string; homeUrl: string; partition: string }
export interface ProviderStatus { id: ProviderId; loading: boolean; canGoBack: boolean; canGoForward: boolean; title: string; error?: string; cleared?: boolean }
export interface TerminalMetadata { id: string; name: string; cwd: string; status: 'running' | 'stopped' | 'exited' | 'failed'; exitCode?: number; history: string[] }
export interface DesktopState { version: 1; workspace: WorkspaceId; selectedProvider: ProviderId; recentProjects: string[]; terminals: TerminalMetadata[]; windowBounds: { width: number; height: number; x?: number; y?: number } }

export interface ContextPack { project: string; cwd: string; branch?: string; gitStatus: string; instructionFiles: Array<{ path: string; content: string }>; skills: string[]; memories: Array<{ id: string; kind: string; summary: string }>; brainContext?: string; assembledAt: string; warnings: string[] }
export interface RunApproval { id: string; requestId: string | number; method: string; status: 'pending' | 'approved' | 'denied'; title: string; detail: string; createdAt: string; providerPayload: unknown }
export interface RunEvidence { branch?: string; gitStatusBefore?: string; gitStatusAfter?: string; changedFiles: string[]; diff?: string; tests: Array<{ command: string; exitCode: number | null; output: string }>; finalMessage?: string }
export interface ProofState { local: 'not_saved' | 'saved'; brain: 'not_attempted' | 'saved' | 'unavailable' | 'failed'; detail?: string; path?: string }
export interface WardenRun { id: string; provider: string; model?: string; project: string; cwd: string; prompt: string; status: 'starting' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled' | 'interrupted'; threadId?: string; turnId?: string; createdAt: string; updatedAt: string; context?: ContextPack; events: NormalizedRunEvent[]; approvals: RunApproval[]; evidence: RunEvidence; proof: ProofState; error?: string }

export type NormalizedRunEventType = 'run.started' | 'message.delta' | 'tool.started' | 'tool.completed' | 'approval.requested' | 'file.changed' | 'command.started' | 'command.completed' | 'test.completed' | 'run.completed' | 'run.failed' | 'run.cancelled';
export interface NormalizedRunEvent { type: NormalizedRunEventType; runId: string; provider: string; timestamp: string; payload: Record<string, unknown>; providerPayload?: unknown }
export interface ProviderCapabilities { streaming: boolean; approvals: boolean; resume: boolean; cancellation: boolean; toolEvents: boolean; fileChanges: boolean; usage: boolean }
export interface StartRunInput { prompt: string; project: string; workingDirectory: string; model?: string; threadId?: string; context?: ContextPack }
export interface ResumeRunInput { runId: string; prompt?: string }
export interface ApprovalResponse { runId: string; approvalId: string; decision: 'approve' | 'deny'; scope?: 'once' | 'session' }
export interface RunHandle { runId: string; threadId?: string; provider: string }
export type RunEventListener = (event: NormalizedRunEvent) => void;
export type Unsubscribe = () => void;
export interface BuildProvider {
  readonly id: string;
  capabilities(): ProviderCapabilities;
  startRun(input: StartRunInput): Promise<RunHandle>;
  resumeRun(input: ResumeRunInput): Promise<RunHandle>;
  cancelRun(runId: string): Promise<void>;
  respondToApproval(input: ApprovalResponse): Promise<void>;
  subscribe(runId: string, listener: RunEventListener): Unsubscribe;
}

export interface DesktopApi {
  state: { get(): Promise<{ state: DesktopState; warning?: string }>; update(patch: Partial<Pick<DesktopState, 'workspace' | 'selectedProvider'>>): Promise<DesktopState> };
  provider: { show(id: ProviderId): Promise<void>; hide(): Promise<void>; action(id: ProviderId, action: 'back' | 'forward' | 'reload' | 'stop' | 'home'): Promise<void>; clearSession(id: ProviderId): Promise<void>; setBounds(bounds: { x: number; y: number; width: number; height: number }): void; onStatus(listener: (status: ProviderStatus) => void): () => void };
  terminal: { list(): Promise<TerminalMetadata[]>; chooseDirectory(): Promise<string | null>; create(input: { name: string; cwd: string; restoreId?: string }): Promise<TerminalMetadata>; write(id: string, data: string): void; resize(id: string, cols: number, rows: number): void; kill(id: string): Promise<void>; clearHistory(id: string): Promise<void>; recordCommand(id: string, command: string): Promise<void>; onData(listener: (payload: { id: string; data: string }) => void): () => void; onState(listener: (terminal: TerminalMetadata) => void): () => void };
  runs: { list(): Promise<WardenRun[]>; get(id: string): Promise<WardenRun>; previewContext(cwd: string): Promise<ContextPack>; start(input: { prompt: string; cwd: string; attachContext: boolean; model?: string }): Promise<WardenRun>; resume(id: string, prompt: string): Promise<WardenRun>; cancel(id: string): Promise<void>; approve(runId: string, approvalId: string, decision: 'approve' | 'deny', scope?: 'once' | 'session'): Promise<void>; handoff(id: string): Promise<{ path: string; content: string }>; saveProof(id: string): Promise<ProofState>; onChanged(listener: (run: WardenRun) => void): () => void };
}
