import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { ContextPack, NormalizedRunEvent, ProofState, RunApproval, WardenRun } from '../shared/types';
import { redact } from './redaction';

function atomicJson(path: string, value: unknown): void { mkdirSync(join(path, '..'), { recursive: true }); const temp = `${path}.tmp`; writeFileSync(temp, JSON.stringify(value, null, 2), { mode: 0o600 }); renameSync(temp, path); }
export class RunStore {
  readonly root: string;
  constructor(userData: string) { this.root = join(userData, 'runs'); mkdirSync(this.root, { recursive: true }); }
  private path(id: string): string { if (!/^[\w-]{1,100}$/.test(id)) throw new Error('Invalid run ID.'); return join(this.root, id, 'run.json'); }
  list(): WardenRun[] { if (!existsSync(this.root)) return []; const index = join(this.root, 'index.json'); if (!existsSync(index)) return []; try { const ids = JSON.parse(readFileSync(index, 'utf8')) as string[]; return ids.map((id) => this.get(id)).filter((run): run is WardenRun => Boolean(run)).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)); } catch { return []; } }
  get(id: string): WardenRun | null { try { return JSON.parse(readFileSync(this.path(id), 'utf8')) as WardenRun; } catch { return null; } }
  create(input: { provider: string; project: string; cwd: string; prompt: string; model?: string; context?: ContextPack }): WardenRun { const now = new Date().toISOString(); const run: WardenRun = { id: `run-${randomUUID()}`, provider: input.provider, model: input.model, project: input.project, cwd: input.cwd, prompt: redact(input.prompt), status: 'starting', createdAt: now, updatedAt: now, context: input.context, events: [], approvals: [], evidence: { branch: input.context?.branch, gitStatusBefore: input.context?.gitStatus, changedFiles: [], tests: [] }, proof: { local: 'not_saved', brain: 'not_attempted' } }; this.save(run); return run; }
  save(run: WardenRun): WardenRun { run.updatedAt = new Date().toISOString(); atomicJson(this.path(run.id), run); const ids = [run.id, ...this.listIds().filter((id) => id !== run.id)].slice(0, 200); atomicJson(join(this.root, 'index.json'), ids); return run; }
  private listIds(): string[] { try { return JSON.parse(readFileSync(join(this.root, 'index.json'), 'utf8')) as string[]; } catch { return []; } }
  update(id: string, patch: Partial<WardenRun>): WardenRun { const run = this.get(id); if (!run) throw new Error('Run not found.'); Object.assign(run, patch); return this.save(run); }
  appendEvent(id: string, event: NormalizedRunEvent): WardenRun { const run = this.get(id); if (!run) throw new Error('Run not found.'); run.events.push(JSON.parse(redact(JSON.stringify(event))) as NormalizedRunEvent); run.events = run.events.slice(-2000); return this.save(run); }
  addApproval(id: string, approval: RunApproval): WardenRun { const run = this.get(id); if (!run) throw new Error('Run not found.'); run.approvals.push(JSON.parse(redact(JSON.stringify(approval))) as RunApproval); run.status = 'waiting_approval'; return this.save(run); }
  resolveApproval(id: string, approvalId: string, status: 'approved' | 'denied'): WardenRun { const run = this.get(id); if (!run) throw new Error('Run not found.'); const approval = run.approvals.find((item) => item.id === approvalId); if (!approval) throw new Error('Approval not found.'); approval.status = status; if (!run.approvals.some((item) => item.status === 'pending')) run.status = 'running'; return this.save(run); }
  saveArtifact(id: string, filename: string, content: string): string { const path = join(this.root, id, filename); mkdirSync(join(path, '..'), { recursive: true }); writeFileSync(path, redact(content), { mode: 0o600 }); return path; }
  setProof(id: string, proof: ProofState): WardenRun { return this.update(id, { proof }); }
}
