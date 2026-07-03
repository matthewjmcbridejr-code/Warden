"""Bounded, safe command execution for WebStudio workflows.

All commands run with a timeout and never raise on failure — callers get a
structured CommandResult instead. No shell string interpolation: commands are
always passed as argv lists.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_TIMEOUT_SECONDS = 180


@dataclass
class CommandResult:
    args: list[str]
    cwd: str
    returncode: Optional[int]
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.error is None and self.returncode == 0

    def to_dict(self) -> dict:
        return {
            "args": self.args,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout[-8000:],
            "stderr": self.stderr[-8000:],
            "duration_seconds": round(self.duration_seconds, 3),
            "timed_out": self.timed_out,
            "error": self.error,
            "ok": self.ok,
        }


def run_command(
    args: list[str],
    *,
    cwd: Path | str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    env: Optional[dict[str, str]] = None,
) -> CommandResult:
    """Run a command as an argv list (never via shell=True) with a hard timeout."""
    if not args:
        raise ValueError("run_command requires a non-empty argv list")
    cwd_str = str(cwd)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            cwd=cwd_str,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return CommandResult(
            args=args,
            cwd=cwd_str,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            duration_seconds=time.monotonic() - start,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            args=args,
            cwd=cwd_str,
            returncode=None,
            stdout=(exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr=(exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
            duration_seconds=time.monotonic() - start,
            timed_out=True,
            error=f"command timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        return CommandResult(
            args=args,
            cwd=cwd_str,
            returncode=None,
            stdout="",
            stderr="",
            duration_seconds=time.monotonic() - start,
            error=f"executable not found: {exc}",
        )
    except OSError as exc:
        return CommandResult(
            args=args,
            cwd=cwd_str,
            returncode=None,
            stdout="",
            stderr="",
            duration_seconds=time.monotonic() - start,
            error=str(exc),
        )


def run_sequence(
    commands: list[list[str]],
    *,
    cwd: Path | str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    stop_on_failure: bool = True,
) -> list[CommandResult]:
    """Run a sequence of commands, stopping after the first failure by default."""
    results: list[CommandResult] = []
    for args in commands:
        result = run_command(args, cwd=cwd, timeout=timeout)
        results.append(result)
        if stop_on_failure and not result.ok:
            break
    return results
