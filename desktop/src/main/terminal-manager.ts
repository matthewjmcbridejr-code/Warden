import { randomUUID } from 'node:crypto';
import { statSync } from 'node:fs';
import process from 'node:process';
import * as pty from 'node-pty';
import type { BrowserWindow } from 'electron';
import type { TerminalMetadata } from '../shared/types';
import type { StateStore } from './state-store';

type Session = { process: pty.IPty; metadata: TerminalMetadata };
export function validateDirectory(cwd: unknown): string {
  if (typeof cwd !== 'string' || !cwd.startsWith('/') || cwd.length > 4096) throw new Error('Choose an absolute project directory.');
  let stat; try { stat = statSync(cwd); } catch { throw new Error('Project directory does not exist.'); }
  if (!stat.isDirectory()) throw new Error('Selected project path is not a directory.');
  return cwd;
}
export class TerminalManager {
  private sessions = new Map<string, Session>();
  constructor(private readonly window: BrowserWindow, private readonly store: StateStore) {}
  list(): TerminalMetadata[] { return this.store.state.terminals; }
  create(input: { name: string; cwd: string; restoreId?: string }): TerminalMetadata {
    const cwd = validateDirectory(input.cwd); const id = input.restoreId && /^[\w-]{1,80}$/.test(input.restoreId) ? input.restoreId : randomUUID();
    if (this.sessions.has(id)) throw new Error('Terminal session is already running.');
    const prior = this.store.state.terminals.find((item) => item.id === id);
    const metadata: TerminalMetadata = { id, name: String(input.name || 'Terminal').trim().slice(0, 60) || 'Terminal', cwd, status: 'running', history: prior?.history || [] };
    const shell = process.env.SHELL && process.env.SHELL.startsWith('/') ? process.env.SHELL : '/bin/bash';
    const child = pty.spawn(shell, ['-l'], { name: 'xterm-256color', cols: 100, rows: 30, cwd, env: { ...process.env, TERM: 'xterm-256color' } as Record<string, string> });
    this.sessions.set(id, { process: child, metadata }); this.store.upsertTerminal(metadata);
    child.onData((data) => this.window.webContents.send('terminal:data', { id, data }));
    child.onExit(({ exitCode }) => { metadata.status = 'exited'; metadata.exitCode = exitCode; this.sessions.delete(id); this.store.upsertTerminal(metadata); this.window.webContents.send('terminal:state', metadata); });
    return metadata;
  }
  write(id: unknown, data: unknown): void { if (typeof id !== 'string' || typeof data !== 'string' || data.length > 65536) return; this.sessions.get(id)?.process.write(data); }
  resize(id: unknown, cols: unknown, rows: unknown): void { if (typeof id !== 'string' || !Number.isInteger(cols) || !Number.isInteger(rows)) return; if (Number(cols) < 2 || Number(rows) < 1 || Number(cols) > 1000 || Number(rows) > 500) return; this.sessions.get(id)?.process.resize(Number(cols), Number(rows)); }
  kill(id: unknown): void { if (typeof id !== 'string') return; const session = this.sessions.get(id); if (!session) return; session.process.kill(); session.metadata.status = 'stopped'; this.sessions.delete(id); this.store.upsertTerminal(session.metadata); this.window.webContents.send('terminal:state', session.metadata); }
  recordCommand(id: unknown, command: unknown): void { if (typeof id !== 'string' || typeof command !== 'string') return; const meta = this.sessions.get(id)?.metadata || this.store.state.terminals.find((item) => item.id === id); if (!meta) return; const clean = command.trim().slice(0, 4000); if (clean) { meta.history.push(clean); meta.history = meta.history.slice(-200); this.store.upsertTerminal(meta); } }
  clearHistory(id: unknown): void { if (typeof id !== 'string') return; const meta = this.sessions.get(id)?.metadata || this.store.state.terminals.find((item) => item.id === id); if (meta) { meta.history = []; this.store.upsertTerminal(meta); } }
  shutdown(): void { for (const id of [...this.sessions.keys()]) this.kill(id); }
}
