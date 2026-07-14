import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';

export type PlatformAuditEvent = {
  event: string;
  platformId?: string;
  profileId?: string;
  partition?: string;
  contentsId?: number;
  popup?: boolean;
  host?: string;
  protocol?: string;
  mainFrame?: boolean;
  permission?: string;
  outcome?: string;
  errorCode?: number;
  consoleLevel?: string;
  messageHash?: string;
  messageLength?: number;
  anchorX?: number;
  anchorY?: number;
  windowWidth?: number;
  windowHeight?: number;
};

export function safeLocation(rawUrl: string): { host?: string; protocol?: string } {
  try { const url = new URL(rawUrl); return { host: url.hostname.toLowerCase(), protocol: url.protocol }; } catch { return {}; }
}

export function safeMessageFingerprint(message: string): { messageHash: string; messageLength: number } {
  return { messageHash: createHash('sha256').update(message).digest('hex').slice(0, 16), messageLength: message.length };
}

export class PlatformAuditLog {
  readonly file: string;
  constructor(userData: string) { this.file = join(userData, 'diagnostics', 'platform-events.jsonl'); }
  record(event: PlatformAuditEvent): void {
    try {
      mkdirSync(dirname(this.file), { recursive: true });
      if (existsSync(this.file) && statSync(this.file).size > 1_000_000) renameSync(this.file, `${this.file}.previous`);
      appendFileSync(this.file, `${JSON.stringify({ timestamp: new Date().toISOString(), ...event })}\n`, { encoding: 'utf8', mode: 0o600 });
    } catch { /* Diagnostics must never interrupt navigation. */ }
  }
}
