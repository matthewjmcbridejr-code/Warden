import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { clientEnvironment } from './provider-auth';

type JsonObject = Record<string, unknown>;
type Pending = { resolve(value: unknown): void; reject(error: Error): void };
export class CodexRpcClient {
  private process?: ChildProcessWithoutNullStreams; private nextId = 1; private pending = new Map<number, Pending>(); private ready?: Promise<void>;
  onNotification?: (method: string, params: JsonObject) => void;
  onServerRequest?: (id: string | number, method: string, params: JsonObject) => void;
  onStderr?: (message: string) => void;
  async ensureStarted(): Promise<void> { if (this.ready) return this.ready; this.ready = this.start(); return this.ready; }
  private async start(): Promise<void> {
    // Subscription-first: never let launch-environment API credentials override
    // the official Codex login owned by `codex login`.
    this.process = spawn('codex', ['app-server'], { stdio: ['pipe', 'pipe', 'pipe'], env: clientEnvironment('codex', 'subscription'), shell: false });
    this.process.stderr.on('data', (data) => this.onStderr?.(String(data)));
    this.process.on('exit', (code, signal) => { const error = new Error(`Codex App Server exited (${code ?? signal ?? 'unknown'}).`); for (const pending of this.pending.values()) pending.reject(error); this.pending.clear(); this.process = undefined; this.ready = undefined; });
    createInterface({ input: this.process.stdout }).on('line', (line) => this.receive(line));
    await this.request('initialize', { clientInfo: { name: 'warden_ai_desk', title: 'Warden AI Desk', version: '0.1.0' }, capabilities: null });
    this.notify('initialized', {});
  }
  private receive(line: string): void {
    let message: JsonObject; try { message = JSON.parse(line) as JsonObject; } catch { this.onStderr?.(`Non-JSON App Server output: ${line}`); return; }
    if ('method' in message) { const method = String(message.method); const params = (message.params && typeof message.params === 'object' ? message.params : {}) as JsonObject; if ('id' in message && (typeof message.id === 'number' || typeof message.id === 'string')) this.onServerRequest?.(message.id, method, params); else this.onNotification?.(method, params); return; }
    if (typeof message.id === 'number') { const pending = this.pending.get(message.id); if (!pending) return; this.pending.delete(message.id); if (message.error && typeof message.error === 'object') pending.reject(new Error(String((message.error as JsonObject).message || 'Codex App Server request failed.'))); else pending.resolve(message.result); }
  }
  request<T = unknown>(method: string, params: JsonObject): Promise<T> { if (!this.process?.stdin.writable) return Promise.reject(new Error('Codex App Server is not running.')); const id = this.nextId++; return new Promise<T>((resolve, reject) => { this.pending.set(id, { resolve: (value) => resolve(value as T), reject }); this.process!.stdin.write(`${JSON.stringify({ method, id, params })}\n`); }); }
  notify(method: string, params: JsonObject): void { this.process?.stdin.write(`${JSON.stringify({ method, params })}\n`); }
  respond(id: string | number, result: JsonObject): void { this.process?.stdin.write(`${JSON.stringify({ id, result })}\n`); }
  respondError(id: string | number, message: string): void { this.process?.stdin.write(`${JSON.stringify({ id, error: { code: -32601, message } })}\n`); }
  shutdown(): void { this.process?.kill('SIGTERM'); this.process = undefined; this.ready = undefined; }
}
