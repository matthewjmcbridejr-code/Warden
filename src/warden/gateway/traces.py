"""Gateway trace storage — JSONL, no database required."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRACE_FILE = Path(
    os.getenv("WARDEN_GATEWAY_TRACES", "~/.local/share/warden/gateway_traces.jsonl")
).expanduser()

_LOCK = threading.Lock()
MAX_TRACES = 500


@dataclass
class GatewayTrace:
    trace_id: str
    task_preview: str           # first 120 chars of input
    alias: str
    provider: str
    model: str
    classifier_used: str
    tools_called: list[str]
    fallback_used: bool
    tokens_before: int
    tokens_after: int
    privacy: str
    openrouter_free_blocked: bool
    privacy_block_reason: str
    status: str                 # "ok" | "error" | "fallback"
    elapsed_ms: int
    timestamp: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def record(trace: GatewayTrace) -> None:
    TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    row = json.dumps(asdict(trace), default=str)
    with _LOCK:
        with TRACE_FILE.open("a", encoding="utf-8") as f:
            f.write(row + "\n")
        _prune()


def _prune() -> None:
    """Keep only the last MAX_TRACES entries."""
    try:
        lines = TRACE_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_TRACES:
            TRACE_FILE.write_text("\n".join(lines[-MAX_TRACES:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def recent(limit: int = 50) -> list[dict[str, Any]]:
    if not TRACE_FILE.exists():
        return []
    try:
        lines = TRACE_FILE.read_text(encoding="utf-8").splitlines()
        rows = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
            if len(rows) >= limit:
                break
        return rows
    except Exception:
        return []


def make_trace_id() -> str:
    import uuid
    return f"gt_{uuid.uuid4().hex[:10]}"
