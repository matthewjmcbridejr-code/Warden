import os
import sys
import json
import uuid
import subprocess
import threading
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Dict
from .contracts import WorkerRun, WorkerResult

from src.warden.paths import data_root as _warden_data_root
MCTABLE_ROOT = _warden_data_root()
RUNS_DIR = MCTABLE_ROOT / "worker_runs"

# Allowlist definition
ALLOWED_COMMANDS = {
    "fake-worker-success",
    "fake-worker-fail",
    "fake-worker-sleep",
    "grok-build-stub",
    "codex-stub",
    "agy"
}

# Global dictionary to keep track of running processes in memory
ACTIVE_PROCESSES: Dict[str, subprocess.Popen] = {}
ACTIVE_MONITORS: Dict[str, threading.Thread] = {}
ACTIVE_CANCEL_EVENTS: Dict[str, threading.Event] = {}

# File lock for thread-safe worker run state reads and writes
FILE_LOCK = threading.Lock()

class WorkerStub:
    @staticmethod
    def start_run(agent_id: str, task_id: str, command: str, args: List[str]) -> str:
        if command not in ALLOWED_COMMANDS:
            raise ValueError(f"Command '{command}' is not allowlisted.")

        if command == "agy":
            raise ValueError("Command 'agy' is registered as disabled/dry-run only.")

        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)

        # Initialize log paths
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"

        # Handle stubs synchronously/immediately
        if command in ["grok-build-stub", "codex-stub"]:
            stdout_path.write_text("Stub command executed.\n", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")

            run_info = WorkerRun(
                run_id=run_id,
                task_id=task_id,
                agent_id=agent_id,
                command=command,
                args=args,
                status="success",
                exit_code=0,
                logs_path=str(run_dir),
                started_at=now,
                finished_at=now
            )
            with FILE_LOCK:
                with open(run_dir / "run.json", "w", encoding="utf-8") as f:
                    f.write(run_info.model_dump_json(indent=2))

            result = WorkerResult(
                run_id=run_id,
                task_id=task_id,
                status="success",
                summary=f"Stub command '{command}' succeeded.",
                artifacts=[str(stdout_path)],
                next_actions=[],
                recovery_hint=None,
                raw_output_path=str(stdout_path)
            )
            with FILE_LOCK:
                with open(run_dir / "result.json", "w", encoding="utf-8") as f:
                    f.write(result.model_dump_json(indent=2))

            return run_id

        # Mapping for fake-worker subprocess
        sub_arg = ""
        if command == "fake-worker-success":
            sub_arg = "success"
        elif command == "fake-worker-fail":
            sub_arg = "fail"
        elif command == "fake-worker-sleep":
            sub_arg = "sleep"

        # Sanitize env to only allow safe keys (security hardening)
        safe_keys = {"PATH", "HOME", "USER", "LANG", "TERM", "SHELL"}
        clean_env = {k: v for k, v in os.environ.items() if k in safe_keys}

        # Open files for stdout and stderr redirection
        stdout_file = open(stdout_path, "w", encoding="utf-8")
        stderr_file = open(stderr_path, "w", encoding="utf-8")
        cancel_event = threading.Event()

        # Command construction (safe subprocess call)
        cmd = [sys.executable, "scripts/fake_worker.py", sub_arg]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=stdout_file,
                stderr=stderr_file,
                env=clean_env,
                cwd=str(Path.cwd())
            )
            ACTIVE_PROCESSES[run_id] = proc
        except Exception as exc:
            stdout_file.close()
            stderr_file.close()
            raise RuntimeError(f"Failed to spawn subprocess: {exc}")

        # Save initial run.json (include pid for validation)
        run_info = WorkerRun(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            command=command,
            args=args,
            status="running",
            exit_code=None,
            logs_path=str(run_dir),
            started_at=now,
            finished_at=None
        )

        run_dict = json.loads(run_info.model_dump_json())
        run_dict["pid"] = proc.pid

        with FILE_LOCK:
            with open(run_dir / "run.json", "w", encoding="utf-8") as f:
                json.dump(run_dict, f, indent=2)

        # Start a background thread to wait and clean up when process exits
        def monitor():
            try:
                exit_code = proc.wait()
            finally:
                stdout_file.close()
                stderr_file.close()

            # Remove from active registries before any finalization writes.
            with FILE_LOCK:
                ACTIVE_PROCESSES.pop(run_id, None)
                ACTIVE_MONITORS.pop(run_id, None)
                ACTIVE_CANCEL_EVENTS.pop(run_id, None)

            if cancel_event.is_set():
                return

            with FILE_LOCK:
                if not run_dir.exists():
                    return

                # Read current run.json state (it might have been cancelled)
                run_json = run_dir / "run.json"
                try:
                    with open(run_json, "r", encoding="utf-8") as f:
                        curr_data = json.load(f)
                except Exception:
                    curr_data = run_dict

                if curr_data.get("status") == "cancelled":
                    return

                finished_now = datetime.now(timezone.utc)
                status = "success" if exit_code == 0 else "failed"
                curr_data["status"] = status
                curr_data["exit_code"] = exit_code
                curr_data["finished_at"] = finished_now.isoformat().replace("+00:00", "Z")

                with open(run_json, "w", encoding="utf-8") as f:
                    json.dump(curr_data, f, indent=2)

                # Write result.json
                res_status = "success" if exit_code == 0 else "failed"
                summary = "Fake worker succeeded." if exit_code == 0 else "Fake worker failed deliberately."
                recovery_hint = None if exit_code == 0 else "Use fake-worker-success command to bypass failure."

                result = WorkerResult(
                    run_id=run_id,
                    task_id=task_id,
                    status=res_status,
                    summary=summary,
                    artifacts=[str(stdout_path), str(stderr_path)],
                    next_actions=["complete_task"] if exit_code == 0 else ["debug"],
                    recovery_hint=recovery_hint,
                    raw_output_path=str(stdout_path) if exit_code == 0 else str(stderr_path)
                )
                with open(run_dir / "result.json", "w", encoding="utf-8") as f:
                    f.write(result.model_dump_json(indent=2))

        thread = threading.Thread(target=monitor, daemon=True)
        with FILE_LOCK:
            ACTIVE_MONITORS[run_id] = thread
            ACTIVE_CANCEL_EVENTS[run_id] = cancel_event
        thread.start()

        return run_id

    @staticmethod
    def get_status(run_id: str) -> WorkerRun:
        run_dir = RUNS_DIR / run_id
        run_json = run_dir / "run.json"

        with FILE_LOCK:
            if not run_json.exists():
                raise FileNotFoundError(f"Worker run {run_id} not found.")

            with open(run_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            status = data.get("status")
            pid = data.get("pid")

            # Check process liveness if status is running
            if status == "running":
                is_alive = False
                proc = ACTIVE_PROCESSES.get(run_id)
                if proc:
                    poll_res = proc.poll()
                    is_alive = (poll_res is None)
                else:
                    if pid:
                        try:
                            os.kill(pid, 0)
                            is_alive = True
                        except OSError:
                            is_alive = False

                if not is_alive:
                    exit_code = 1
                    if proc:
                        exit_code = proc.poll() or 0

                    now = datetime.now(timezone.utc)
                    data["status"] = "success" if exit_code == 0 else "failed"
                    data["exit_code"] = exit_code
                    data["finished_at"] = now.isoformat().replace("+00:00", "Z")

                    with open(run_json, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)

                    res_status = "success" if exit_code == 0 else "failed"
                    summary = "Fake worker succeeded." if exit_code == 0 else "Fake worker failed."
                    recovery_hint = None if exit_code == 0 else "Use fake-worker-success command to bypass failure."
                    result = WorkerResult(
                        run_id=run_id,
                        task_id=data["task_id"],
                        status=res_status,
                        summary=summary,
                        artifacts=[str(run_dir / "stdout.log"), str(run_dir / "stderr.log")],
                        next_actions=[],
                        recovery_hint=recovery_hint,
                        raw_output_path=str(run_dir / "stdout.log")
                    )
                    with open(run_dir / "result.json", "w", encoding="utf-8") as f:
                        f.write(result.model_dump_json(indent=2))

            # Re-read to ensure we return the latest state
            with open(run_json, "r", encoding="utf-8") as f:
                data = json.load(f)

        data.pop("pid", None)
        return WorkerRun(**data)

    @staticmethod
    def stream_logs(run_id: str) -> Iterator[str]:
        run_dir = RUNS_DIR / run_id
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"

        with FILE_LOCK:
            logs = []
            if stdout_path.exists():
                logs.append(stdout_path.read_text(encoding="utf-8"))
            if stderr_path.exists():
                logs.append(stderr_path.read_text(encoding="utf-8"))

        yield "\n".join(logs)

    @staticmethod
    def cancel_run(run_id: str) -> None:
        run_dir = RUNS_DIR / run_id
        run_json = run_dir / "run.json"
        monitor_thread = None
        cancel_event = None
        proc = None

        with FILE_LOCK:
            if not run_json.exists():
                raise FileNotFoundError(f"Worker run {run_id} not found.")

            with open(run_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            if data["status"] in ["running", "queued"]:
                proc = ACTIVE_PROCESSES.pop(run_id, None)
                monitor_thread = ACTIVE_MONITORS.get(run_id)
                cancel_event = ACTIVE_CANCEL_EVENTS.get(run_id)

                if cancel_event:
                    cancel_event.set()

        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
            except Exception:
                pass
        else:
            pid = data.get("pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass

        if monitor_thread:
            monitor_thread.join()

        now = datetime.now(timezone.utc)
        data["status"] = "cancelled"
        data["exit_code"] = -1
        data["finished_at"] = now.isoformat().replace("+00:00", "Z")

        with FILE_LOCK:
            with open(run_json, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            result = WorkerResult(
                run_id=run_id,
                task_id=data["task_id"],
                status="cancelled",
                summary="Worker run was cancelled.",
                artifacts=[],
                next_actions=["review_cancel_reason"],
                recovery_hint="Task cancelled by operator.",
                raw_output_path=None
            )
            with open(run_dir / "result.json", "w", encoding="utf-8") as f:
                f.write(result.model_dump_json(indent=2))
