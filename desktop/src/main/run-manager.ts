import { basename } from 'node:path';
import type { BrowserWindow } from 'electron';
import type { BuildProvider, ContextPack, ProofState, ProviderAuthReport, StructuredProviderId, WardenRun } from '../shared/types';
import { StructuredCliProvider } from './cli-provider';
import { CodexAppServerProvider } from './codex-adapter';
import { assembleContext } from './context-assembler';
import { collectEvidence } from './evidence';
import { discardSafeWorkspace, GitSafeLoopError, isCleanGitProject, keepSafeWorkspace, startSafeWorkspace, undoConsolidatedCommit } from './git-safe-loop';
import { createHandoff } from './handoff';
import { RunStore } from './run-store';
import { validateDirectory } from './terminal-manager';

export class RunManager {
  readonly store: RunStore;
  readonly providers: Record<StructuredProviderId, BuildProvider>;

  constructor(userData: string, private readonly window: BrowserWindow) {
    this.store = new RunStore(userData);
    for (const run of this.store.list()) if (['starting', 'running', 'waiting_approval'].includes(run.status)) this.store.update(run.id, { status: 'interrupted', error: `Warden AI Desk restarted while this ${run.provider} run was active. Resume the preserved provider session to continue.` });
    const changed = (run: WardenRun): void => { if (!this.window.isDestroyed() && !this.window.webContents.isDestroyed()) this.window.webContents.send('runs:changed', run); };
    this.providers = {
      codex: new CodexAppServerProvider(this.store, changed),
      claude: new StructuredCliProvider('claude', this.store, changed),
      gemini: new StructuredCliProvider('gemini', this.store, changed),
      grok: new StructuredCliProvider('grok', this.store, changed),
    };
  }

  async providerStatus(): Promise<ProviderAuthReport[]> { return Promise.all((Object.keys(this.providers) as StructuredProviderId[]).map((id) => this.providers[id].authStatus())); }
  checkProject(cwd: string): Promise<{ isGit: boolean; clean: boolean }> { return isCleanGitProject(validateDirectory(cwd)); }
  list(projectId?: string): WardenRun[] { const runs = this.store.list(); return projectId ? runs.filter((run) => run.projectId === projectId || (!run.projectId && run.cwd === projectId)) : runs; }
  get(id: string): WardenRun { const run = this.store.get(id); if (!run) throw new Error('Run not found.'); return run; }
  private providerFor(run: WardenRun): BuildProvider { const provider = this.providers[run.provider as StructuredProviderId]; if (!provider) throw new Error(`No structured adapter for ${run.provider}.`); return provider; }

  async previewContext(cwd: string, prompt = ''): Promise<ContextPack> {
    const pack = await assembleContext(cwd); const base = process.env.WARDEN_PRIVATE_URL || 'http://127.0.0.1:8125'; const projectId = basename(cwd).replace(/[^A-Za-z0-9_.-]/g, '-').slice(0, 160) || 'project';
    try {
      const response = await fetch(`${base}/api/mcharness/memory/context-pack`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ project_id: projectId, repo_path: cwd, agent: 'warden_ai_desk', prompt, branch: pack.branch, max_memories: 8, max_chars: 6000 }), signal: AbortSignal.timeout(2500) });
      const body = await response.json().catch(() => ({})) as Record<string, unknown>;
      if (response.ok && body.ok === true && typeof body.context === 'string') pack.brainContext = body.context; else pack.warnings.push(`Warden Brain context unavailable (${response.status}).`);
    } catch { pack.warnings.push('Warden Brain context unavailable; using repository-local context only.'); }
    return pack;
  }

  async start(input: { provider: StructuredProviderId; prompt: string; cwd: string; projectId?: string; attachContext: boolean; model?: string; authSource: 'subscription' | 'api_key'; apiFallbackApproved?: boolean; safe?: boolean }): Promise<WardenRun> {
    const projectCwd = validateDirectory(input.cwd); const prompt = String(input.prompt || '').trim();
    if (!prompt || prompt.length > 100_000) throw new Error('Enter a build prompt under 100,000 characters.');
    const provider = this.providers[input.provider]; if (!provider) throw new Error('Unknown structured provider.');

    // D1: Simple Mode runs Codex inside an isolated safe workspace, never
    // the real project directory. input.safe is only honored for Codex —
    // Claude/Gemini/Grok get parity in Phase 3.
    let workingDirectory = projectCwd; let safeWorkspace: WardenRun['safeWorkspace'];
    if (input.safe && input.provider === 'codex') {
      safeWorkspace = await startSafeWorkspace(projectCwd);
      workingDirectory = safeWorkspace.worktreePath;
    }

    const context = input.attachContext ? await this.previewContext(workingDirectory, prompt) : undefined;
    try {
      const handle = await provider.startRun({ prompt, project: basename(projectCwd), projectId: input.projectId, workingDirectory, projectCwd: safeWorkspace ? projectCwd : undefined, safeWorkspace, model: input.model, context, authSource: input.authSource, apiFallbackApproved: input.apiFallbackApproved });
      return this.get(handle.runId);
    } catch (error) {
      if (safeWorkspace) await discardSafeWorkspace(projectCwd, safeWorkspace).catch(() => undefined);
      throw error;
    }
  }

  async resume(id: string, prompt: string): Promise<WardenRun> { const run = this.get(id); await this.providerFor(run).resumeRun({ runId: id, prompt: String(prompt || '').trim() || undefined }); return this.get(id); }
  cancel(id: string): Promise<void> { const run = this.get(id); return this.providerFor(run).cancelRun(id); }
  approve(runId: string, approvalId: string, decision: 'approve' | 'deny', scope?: 'once' | 'session'): Promise<void> { const run = this.get(runId); return this.providerFor(run).respondToApproval({ runId, approvalId, decision, scope }); }

  /** Keep changes — consolidate the safe workspace into one saved version on the real project. Never pushes remotely. */
  async keep(id: string): Promise<WardenRun> {
    const run = this.get(id);
    if (!run.safeWorkspace || !run.projectCwd) throw new Error('This task has no safe workspace to keep.');
    if (run.status === 'running' || run.status === 'starting' || run.status === 'waiting_approval') throw new Error('Wait for the task to finish before keeping changes.');
    const summary = run.evidence.finalMessage?.slice(0, 200) || `Warden update: ${run.prompt.slice(0, 120)}`;
    let safeWorkspace;
    try { safeWorkspace = await keepSafeWorkspace(run.projectCwd, run.safeWorkspace, summary); }
    catch (error) { throw error instanceof GitSafeLoopError ? error : new Error(error instanceof Error ? error.message : String(error)); }
    const updated = this.store.update(id, { safeWorkspace }); if (!this.window.isDestroyed() && !this.window.webContents.isDestroyed()) this.window.webContents.send('runs:changed', updated); return updated;
  }

  /** Discard (pre-acceptance) — tears down the isolated worktree only; the real project is never touched. */
  async discard(id: string): Promise<WardenRun> {
    const run = this.get(id);
    if (!run.safeWorkspace || !run.projectCwd) throw new Error('This task has no safe workspace to discard.');
    const safeWorkspace = await discardSafeWorkspace(run.projectCwd, run.safeWorkspace);
    const updated = this.store.update(id, { safeWorkspace }); if (!this.window.isDestroyed() && !this.window.webContents.isDestroyed()) this.window.webContents.send('runs:changed', updated); return updated;
  }

  /** Undo this update (post-acceptance) — a reversible revert, never a destructive reset. */
  async undoUpdate(id: string): Promise<WardenRun> {
    const run = this.get(id);
    if (!run.safeWorkspace || !run.projectCwd) throw new Error('This task has no saved update to undo.');
    await undoConsolidatedCommit(run.projectCwd, run.safeWorkspace);
    return run;
  }
  async handoff(id: string): Promise<{ path: string; content: string }> { let run = this.get(id); run = this.store.update(id, { evidence: await collectEvidence(run) }); const content = createHandoff(run); return { path: this.store.saveArtifact(id, 'handoff.md', content), content }; }

  async saveProof(id: string): Promise<ProofState> {
    let run = this.get(id); run = this.store.update(id, { evidence: await collectEvidence(run) });
    const content = [`Warden AI Desk proof`, `Run: ${run.id}`, `Provider: ${run.provider}`, `Authentication: ${run.auth?.source || 'unknown'} (${run.auth?.entitlement || run.auth?.state || 'unreported'})`, `Status: ${run.status}`, `Project: ${run.project}`, `Branch: ${run.evidence.branch || run.context?.branch || 'unknown'}`, `Changed files: ${run.evidence.changedFiles.join(', ') || 'none'}`, `Tests: ${run.evidence.tests.map((test) => `${test.command} => ${test.exitCode}`).join('; ') || 'none recorded'}`, `Result: ${run.evidence.finalMessage || run.error || 'none'}`].join('\n');
    const path = this.store.saveArtifact(id, 'proof.txt', content); let proof: ProofState = { local: 'saved', brain: 'unavailable', path, detail: 'Saved locally. Warden private Brain service is unavailable.' }; const base = process.env.WARDEN_PRIVATE_URL || 'http://127.0.0.1:8125';
    try {
      const response = await fetch(`${base}/api/mcharness/memory/remember`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ scope: 'warden', content, source: 'warden_ai_desk', title: `Proof: ${run.project} ${run.id}`, tags: ['desktop', run.provider, 'proof'], kind: 'proof', project_id: run.project, repo_path: run.cwd, branch: run.evidence.branch || run.context?.branch, agent_id: run.provider, metadata: { run_id: run.id, thread_id: run.threadId, auth_source: run.auth?.source } }), signal: AbortSignal.timeout(3000) });
      const body = await response.json().catch(() => ({})) as Record<string, unknown>;
      if (response.ok && body.ok === true) proof = { local: 'saved', brain: 'saved', path, detail: 'Saved locally and to Warden Brain.' }; else proof = { local: 'saved', brain: 'failed', path, detail: `Brain rejected proof (${response.status}): ${String(body.error || body.detail || 'unknown error')}` };
    } catch (error) { proof = { local: 'saved', brain: 'unavailable', path, detail: `Saved locally; Brain unavailable: ${error instanceof Error ? error.message : String(error)}` }; }
    this.store.setProof(id, proof); if (!this.window.isDestroyed() && !this.window.webContents.isDestroyed()) this.window.webContents.send('runs:changed', this.get(id)); return proof;
  }

  shutdown(): void { for (const provider of Object.values(this.providers)) { const candidate = provider as BuildProvider & { shutdown?(): void }; candidate.shutdown?.(); } }
}
