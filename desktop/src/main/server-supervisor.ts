import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

export class ServerSupervisor {
  private child: ChildProcess | null = null;
  private startedByUs = false;
  private startPromise: Promise<boolean> | null = null;
  private lastError: string | null = null;

  async ensureRunning(): Promise<boolean> {
    if (await this.isHealthy()) return true;

    if (this.startPromise) {
      return this.startPromise;
    }

    this.startPromise = this._startInternal().finally(() => {
      this.startPromise = null;
    });

    return this.startPromise;
  }

  private async _startInternal(): Promise<boolean> {
    if (await this.isHealthy()) return true;

    const candidatePaths = [
      process.env.VIRTUAL_ENV ? join(process.env.VIRTUAL_ENV, 'bin', 'python') : null,
      join(process.cwd(), '.venv', 'bin', 'python'),
      join(process.cwd(), '..', '.venv', 'bin', 'python'),
      '/home/matt/workspaces/warden/mcharness-public-export/.venv/bin/python',
      '/usr/bin/python3',
    ].filter(Boolean) as string[];

    let pythonBin: string | null = null;
    let repoRoot: string | null = null;

    for (const p of candidatePaths) {
      if (existsSync(p)) {
        const possibleRoots = [
          resolve(p, '..', '..'),
          process.cwd(),
          resolve(process.cwd(), '..'),
          '/home/matt/workspaces/warden/mcharness-public-export',
        ];
        for (const root of possibleRoots) {
          if (existsSync(join(root, 'src', 'warden', 'app.py'))) {
            pythonBin = p;
            repoRoot = root;
            break;
          }
        }
        if (pythonBin && repoRoot) break;
      }
    }

    if (!pythonBin || !repoRoot) {
      this.lastError = 'Python environment or Warden repository root could not be located.';
      return false;
    }

    try {
      this.lastError = null;
      const pythonPath = `${repoRoot}:${join(repoRoot, 'src')}`;
      this.child = spawn(
        pythonBin,
        ['-m', 'uvicorn', 'src.warden.app:app', '--host', '127.0.0.1', '--port', '6969', '--log-level', 'warning'],
        {
          cwd: repoRoot,
          env: {
            ...process.env,
            PYTHONPATH: pythonPath,
            MCHARNESS_LOCAL_DEV: '1',
            WARDEN_LOCAL_DESK: '1',
            MCHARNESS_PUBLIC_WRITE: '1',
          },
          stdio: 'pipe',
        }
      );
      this.startedByUs = true;

      this.child.on('error', (err) => {
        this.lastError = `Server failed to spawn: ${err.message}`;
        console.error('[warden supervisor] Server failed to spawn:', err);
      });

      this.child.on('exit', (code, sig) => {
        if (this.startedByUs) {
          console.log(`[warden supervisor] Server process exited (code=${code}, sig=${sig})`);
        }
        this.child = null;
      });

      // Poll until healthy or deadline (up to 12s)
      const deadline = Date.now() + 12000;
      while (Date.now() < deadline) {
        if (await this.isHealthy()) return true;
        await new Promise((r) => setTimeout(r, 250));
      }

      const finalHealth = await this.isHealthy();
      if (!finalHealth && !this.lastError) {
        this.lastError = 'Server process started but did not respond to health checks in time.';
      }
      return finalHealth;
    } catch (e) {
      this.lastError = e instanceof Error ? e.message : String(e);
      console.error('[warden supervisor] Failed to start server:', e);
      return false;
    }
  }

  async isHealthy(): Promise<boolean> {
    try {
      const res = await fetch('http://127.0.0.1:6969/api/mcharness/health', { signal: AbortSignal.timeout(600) });
      return res.ok;
    } catch {
      return false;
    }
  }

  getStatus(): { healthy: boolean; starting: boolean; error: string | null } {
    return {
      healthy: this.child !== null || false,
      starting: this.startPromise !== null,
      error: this.lastError,
    };
  }

  shutdown(): void {
    if (this.child && this.startedByUs) {
      try {
        this.child.kill('SIGTERM');
      } catch {}
      this.child = null;
    }
  }
}
