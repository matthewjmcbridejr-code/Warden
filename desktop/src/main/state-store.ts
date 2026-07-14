import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import type { DesktopState, ProviderId, TerminalMetadata, WorkspaceId } from '../shared/types';

const defaults: DesktopState = { version: 1, workspace: 'chat', selectedProvider: 'claude', recentProjects: [], terminals: [], windowBounds: { width: 1440, height: 920 } };
function isProvider(value: unknown): value is ProviderId { return ['claude', 'chatgpt', 'gemini', 'grok'].includes(String(value)); }
function isWorkspace(value: unknown): value is WorkspaceId { return value === 'chat' || value === 'build'; }
function cleanTerminal(value: unknown): TerminalMetadata | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Partial<TerminalMetadata>;
  if (typeof item.id !== 'string' || typeof item.name !== 'string' || typeof item.cwd !== 'string') return null;
  return { id: item.id, name: item.name.slice(0, 60), cwd: item.cwd, status: 'stopped', history: Array.isArray(item.history) ? item.history.filter((x): x is string => typeof x === 'string').slice(-200) : [] };
}

export class StateStore {
  readonly file: string; state: DesktopState = structuredClone(defaults); warning?: string;
  constructor(userData: string) { this.file = join(userData, 'desktop-state.json'); this.load(); }
  private load(): void {
    if (!existsSync(this.file)) return;
    try {
      const raw = JSON.parse(readFileSync(this.file, 'utf8')) as Partial<DesktopState>;
      this.state = { ...structuredClone(defaults), ...raw, version: 1, workspace: isWorkspace(raw.workspace) ? raw.workspace : 'chat', selectedProvider: isProvider(raw.selectedProvider) ? raw.selectedProvider : 'claude', recentProjects: Array.isArray(raw.recentProjects) ? raw.recentProjects.filter((x): x is string => typeof x === 'string').slice(0, 10) : [], terminals: Array.isArray(raw.terminals) ? raw.terminals.map(cleanTerminal).filter((x): x is TerminalMetadata => Boolean(x)) : [], windowBounds: { ...defaults.windowBounds, ...(raw.windowBounds || {}) } };
    } catch (error) {
      const backup = `${this.file}.corrupt-${Date.now()}`;
      try { copyFileSync(this.file, backup); } catch { /* best effort */ }
      this.warning = `Desktop state was corrupt and reset. A diagnostic copy was saved to ${backup}.`;
      this.state = structuredClone(defaults);
    }
  }
  save(): void { mkdirSync(dirname(this.file), { recursive: true }); const temp = `${this.file}.tmp`; writeFileSync(temp, JSON.stringify(this.state, null, 2), { mode: 0o600 }); renameSync(temp, this.file); }
  patch(patch: Partial<DesktopState>): DesktopState { this.state = { ...this.state, ...patch, version: 1 }; this.save(); return this.state; }
  upsertTerminal(terminal: TerminalMetadata): void { const terminals = this.state.terminals.filter((item) => item.id !== terminal.id); terminals.push({ ...terminal, history: terminal.history.slice(-200) }); this.patch({ terminals }); }
}
