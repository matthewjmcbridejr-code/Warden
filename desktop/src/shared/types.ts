export const providerIds = ['claude', 'chatgpt', 'gemini', 'grok'] as const;
export type ProviderId = typeof providerIds[number];
export type WorkspaceId = 'chat' | 'build';
export type InterfaceMode = 'simple' | 'developer';
export type ExecutionMode = 'local' | 'codex' | 'claude' | 'gemini' | 'grok';
export type StructuredProviderId = Exclude<ExecutionMode, 'local'>;
export type ProviderAuthState = 'subscription_authenticated' | 'api_key_authenticated' | 'disconnected' | 'installed_not_authenticated' | 'unsupported' | 'unknown_entitlement';
export type ProviderAuthSource = 'subscription' | 'api_key' | 'none' | 'unknown';
export interface ProviderDefinition { id: ProviderId; name: string; homeUrl: string; partition: string }
export type ProviderStatus = PlatformStatus;

export type PlatformCategory = 'Chat' | 'Build' | 'Research' | 'Other';
export type PlatformIcon = { kind: 'text' | 'url'; value: string };
export interface BrowserProfile { id: string; name: string; createdAt: string }
export interface WebPlatform {
  id: string;
  name: string;
  startUrl: string;
  category: PlatformCategory;
  icon: PlatformIcon;
  browserProfileId: string;
  projectIds: string[];
  trustedFirstPartyDomains: string[];
  trustedAuthDomains: string[];
  enabled: boolean;
  pinned: boolean;
  order: number;
  allowMainView: boolean;
  allowSplitView: boolean;
  externalLinks: 'ask' | 'system';
  lastUrl?: string;
  createdAt: string;
  updatedAt: string;
}
export interface PlatformPreset { key: string; name: string; startUrl: string; category: PlatformCategory; icon: PlatformIcon; trustedFirstPartyDomains: string[]; trustedAuthDomains: string[] }
export type PlatformNavigationDecision = 'allow_once' | 'trust' | 'external' | 'cancel';
export interface PlatformStatus { id: string; loading: boolean; canGoBack: boolean; canGoForward: boolean; title: string; url?: string; error?: string; cleared?: boolean }
export interface PlatformMenuAction { action: 'settings' | 'split' | 'refresh' | 'removed' | 'cleared'; platformId: string }

export interface ProjectWorkspace {
  id: string;
  name: string;
  cwd: string;
  branch?: string;
  browserProfileId: string;
  selectedPlatformId?: string;
  splitPlatformId?: string;
  workspace: WorkspaceId;
  executionMode: ExecutionMode;
  terminalIds: string[];
  activeRunId?: string;
  updatedAt: string;
}
export interface TerminalMetadata { id: string; name: string; cwd: string; status: 'running' | 'stopped' | 'exited' | 'failed'; exitCode?: number; history: string[] }
export interface DesktopState {
  version: 2;
  onboardingComplete: boolean;
  mode: InterfaceMode;
  workspace: WorkspaceId;
  selectedProvider: ProviderId;
  selectedPlatformId?: string;
  activeProjectId?: string;
  recentProjects: string[];
  projects: ProjectWorkspace[];
  browserProfiles: BrowserProfile[];
  platforms: WebPlatform[];
  removedPlatforms: WebPlatform[];
  terminals: TerminalMetadata[];
  windowBounds: { width: number; height: number; x?: number; y?: number };
}
export interface AppInfo { name: string; version: string; platform: string; arch: string }

export interface ContextPack { project: string; cwd: string; branch?: string; gitStatus: string; instructionFiles: Array<{ path: string; content: string }>; skills: string[]; memories: Array<{ id: string; kind: string; summary: string }>; brainContext?: string; assembledAt: string; warnings: string[] }
export interface RunApproval { id: string; requestId: string | number; method: string; status: 'pending' | 'approved' | 'denied'; title: string; detail: string; createdAt: string; providerPayload: unknown }
export interface RunEvidence { branch?: string; gitStatusBefore?: string; gitStatusAfter?: string; changedFiles: string[]; diff?: string; tests: Array<{ command: string; exitCode: number | null; output: string }>; finalMessage?: string }
export interface ProofState { local: 'not_saved' | 'saved'; brain: 'not_attempted' | 'saved' | 'unavailable' | 'failed'; detail?: string; path?: string }
export interface ProviderAuthReport { provider: StructuredProviderId; state: ProviderAuthState; source: ProviderAuthSource; installed: boolean; client: string; version?: string; entitlement?: string; detail: string; canStart: boolean; apiFallbackAvailable: boolean; checkedAt: string }

// D1 — the safe Git loop for Simple Mode: Codex runs inside an isolated
// worktree, never the real project directory. "Keep changes" consolidates
// into one saved version (never touching a dirty original); "Undo this
// update" reverts the consolidated commit (never `git reset --hard`).
export type SafeWorkspaceStatus = 'active' | 'kept' | 'undone' | 'discarded' | 'conflict';
export interface SafeWorkspace { worktreePath: string; branch: string; baseCommit: string; status: SafeWorkspaceStatus; consolidatedCommit?: string; undoCommit?: string; conflictDetail?: string }

export interface WardenRun { id: string; provider: string; model?: string; project: string; projectId?: string; cwd: string; projectCwd?: string; prompt: string; status: 'starting' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled' | 'interrupted'; auth?: ProviderAuthReport; threadId?: string; turnId?: string; createdAt: string; updatedAt: string; context?: ContextPack; events: NormalizedRunEvent[]; approvals: RunApproval[]; evidence: RunEvidence; proof: ProofState; error?: string; safeWorkspace?: SafeWorkspace }

export type NormalizedRunEventType = 'run.started' | 'message.delta' | 'tool.started' | 'tool.completed' | 'approval.requested' | 'file.changed' | 'command.started' | 'command.completed' | 'test.completed' | 'run.completed' | 'run.failed' | 'run.cancelled';
export interface NormalizedRunEvent { type: NormalizedRunEventType; runId: string; provider: string; timestamp: string; payload: Record<string, unknown>; providerPayload?: unknown }
export interface ProviderCapabilities { streaming: boolean; approvals: boolean; resume: boolean; cancellation: boolean; toolEvents: boolean; fileChanges: boolean; usage: boolean }
export interface StartRunInput { prompt: string; project: string; projectId?: string; workingDirectory: string; projectCwd?: string; safeWorkspace?: SafeWorkspace; model?: string; threadId?: string; context?: ContextPack; authSource: 'subscription' | 'api_key'; apiFallbackApproved?: boolean }
export interface ResumeRunInput { runId: string; prompt?: string }
export interface ApprovalResponse { runId: string; approvalId: string; decision: 'approve' | 'deny'; scope?: 'once' | 'session' }
export interface RunHandle { runId: string; threadId?: string; provider: string }
export type RunEventListener = (event: NormalizedRunEvent) => void;
export type Unsubscribe = () => void;
export interface BuildProvider { readonly id: string; capabilities(): ProviderCapabilities; authStatus(): Promise<ProviderAuthReport>; startRun(input: StartRunInput): Promise<RunHandle>; resumeRun(input: ResumeRunInput): Promise<RunHandle>; cancelRun(runId: string): Promise<void>; respondToApproval(input: ApprovalResponse): Promise<void>; subscribe(runId: string, listener: RunEventListener): Unsubscribe }

export interface DesktopApi {
  app: { info(): Promise<AppInfo> };
  state: { get(): Promise<{ state: DesktopState; warning?: string }>; update(patch: Partial<Pick<DesktopState, 'workspace' | 'selectedProvider' | 'selectedPlatformId' | 'activeProjectId' | 'onboardingComplete' | 'mode'>>): Promise<DesktopState> };
  platform: {
    list(): Promise<WebPlatform[]>; presets(): Promise<PlatformPreset[]>; profiles(): Promise<BrowserProfile[]>; createProfile(name: string): Promise<BrowserProfile>; renameProfile(id: string, name: string): Promise<BrowserProfile>; removeProfile(id: string): Promise<void>;
    create(input: Partial<WebPlatform> & { name: string; startUrl: string }): Promise<WebPlatform>;
    addPreset(key: string, browserProfileId?: string): Promise<WebPlatform>;
    update(id: string, patch: Partial<WebPlatform>): Promise<WebPlatform>;
    remove(id: string): Promise<void>; removed(): Promise<WebPlatform[]>; restore(id: string): Promise<WebPlatform>; restoreDefaults(): Promise<WebPlatform[]>;
    show(id: string, splitId?: string): Promise<void>; hide(): Promise<void>;
    action(id: string, action: 'back' | 'forward' | 'reload' | 'stop' | 'home'): Promise<void>;
    openExternal(id: string): Promise<void>;
    clearSiteData(id: string): Promise<void>;
    showMenu(id: string, anchor: { x: number; y: number }): Promise<void>;
    setBounds(bounds: { x: number; y: number; width: number; height: number }): void;
    onStatus(listener: (status: PlatformStatus) => void): () => void;
    onMenuAction(listener: (action: PlatformMenuAction) => void): () => void;
  };
  project: { list(): Promise<ProjectWorkspace[]>; create(input: { name?: string; cwd: string; browserProfileId?: string }): Promise<ProjectWorkspace>; activate(id: string): Promise<ProjectWorkspace>; update(id: string, patch: Partial<ProjectWorkspace>): Promise<ProjectWorkspace> };
  terminal: { list(): Promise<TerminalMetadata[]>; chooseDirectory(): Promise<string | null>; create(input: { name: string; cwd: string; restoreId?: string }): Promise<TerminalMetadata>; write(id: string, data: string): void; resize(id: string, cols: number, rows: number): void; kill(id: string): Promise<void>; clearHistory(id: string): Promise<void>; recordCommand(id: string, command: string): Promise<void>; onData(listener: (payload: { id: string; data: string }) => void): () => void; onState(listener: (terminal: TerminalMetadata) => void): () => void };
  runs: { providers(): Promise<ProviderAuthReport[]>; checkProject(cwd: string): Promise<{ isGit: boolean; clean: boolean }>; list(projectId?: string): Promise<WardenRun[]>; get(id: string): Promise<WardenRun>; previewContext(cwd: string): Promise<ContextPack>; start(input: { provider: StructuredProviderId; prompt: string; cwd: string; projectId?: string; attachContext: boolean; model?: string; authSource: 'subscription' | 'api_key'; apiFallbackApproved?: boolean; safe?: boolean }): Promise<WardenRun>; resume(id: string, prompt: string): Promise<WardenRun>; cancel(id: string): Promise<void>; approve(runId: string, approvalId: string, decision: 'approve' | 'deny', scope?: 'once' | 'session'): Promise<void>; handoff(id: string): Promise<{ path: string; content: string }>; saveProof(id: string): Promise<ProofState>; keep(id: string): Promise<WardenRun>; discard(id: string): Promise<WardenRun>; undoUpdate(id: string): Promise<WardenRun>; onChanged(listener: (run: WardenRun) => void): () => void };
}
