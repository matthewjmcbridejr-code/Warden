import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

export class ServerSupervisor {
  private child: ChildProcess | null = null;
  private startedByUs = false;

  async ensureRunning(): Promise<boolean> {
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
      return false;
    }

    try {
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
        console.error('[warden supervisor] Server failed to spawn:', err);
      });

      this.child.on('exit', (code, sig) => {
        if (this.startedByUs) {
          console.log(`[warden supervisor] Server process exited (code=${code}, sig=${sig})`);
        }
        this.child = null;
      });

      const deadline = Date.now() + 5000;
      while (Date.now() < deadline) {
        if (await this.isHealthy()) return true;
        await new Promise((r) => setTimeout(r, 200));
      }
      return await this.isHealthy();
    } catch (e) {
      console.error('[warden supervisor] Failed to start server:', e);
      return false;
    }
  }

  async isHealthy(): Promise<boolean> {
    try {
      const res = await fetch('http://127.0.0.1:6969/api/mcharness/health', { signal: AbortSignal.timeout(400) });
      return res.ok;
    } catch {
      return false;
    }
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
