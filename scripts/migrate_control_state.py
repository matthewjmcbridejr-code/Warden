#!/usr/bin/env python3
"""Inventory and migrate Warden's pre-cloud control state.

The cloud-primary adapters make new writes durable in Cloud SQL, but existing
JSON/JSONL/SQLite state still needs an explicit, reviewable migration. This
command is intentionally idempotent: records use their existing IDs and chat
events use their existing idempotency keys. Secret-bearing connector material
is never read or copied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.warden.cloud_control_plane import CloudControlPlane
from src.warden.paths import data_root
from src.warden.run_history import redact_secrets


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _timestamp(payload: dict[str, Any]) -> str:
    value = payload.get("updated_at") or payload.get("decided_at") or payload.get("created_at")
    if isinstance(value, str) and value.strip():
        return value
    return datetime.now(timezone.utc).isoformat()


def _record_id(payload: dict[str, Any], fallback: str) -> str:
    for key in (
        "record_id", "agent_id", "thread_id", "skill_id", "artifact_id", "run_id",
        "evidence_id", "gate_id", "captain_run_id", "plan_id", "conversation_id",
    ):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return fallback


def _safe(value: Any) -> Any:
    """Redact text recursively before it can enter the cloud authority."""
    if isinstance(value, str):
        return redact_secrets(value)[0]
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    return value


def _digest(items: list[tuple[str, str, dict[str, Any]]]) -> str:
    encoded = "\n".join(
        json.dumps({"type": kind, "id": ident, "payload": payload}, sort_keys=True, default=str)
        for kind, ident, payload in sorted(items, key=lambda item: (item[0], item[1]))
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_json_records(root: Path, directory: str, record_type: str) -> list[tuple[str, str, dict[str, Any]]]:
    folder = root / directory
    if not folder.exists():
        return []
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(folder.rglob("*.json")):
        try:
            payload = _safe(_json(path))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        found.append((record_type, _record_id(payload, path.stem), payload))
    return found


def _load_jsonl_records(root: Path, directory: str, record_type: str) -> list[tuple[str, str, dict[str, Any]]]:
    folder = root / directory
    if not folder.exists():
        return []
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(folder.rglob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines):
            try:
                payload = _safe(json.loads(line))
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict):
                found.append((record_type, _record_id(payload, f"{path.stem}_{index}"), payload))
    return found


def _load_index(root: Path, relative: str, record_type: str) -> list[tuple[str, str, dict[str, Any]]]:
    path = root / relative
    if not path.exists():
        return []
    try:
        rows = _json(path)
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(rows, list):
        return []
    found: list[tuple[str, str, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        payload = _safe(row)
        if isinstance(payload, dict):
            found.append((record_type, _record_id(payload, f"{path.stem}_{index}"), payload))
    return found


def _load_chat(db_path: Path) -> tuple[list[tuple[str, str, dict[str, Any]]], list[dict[str, Any]]]:
    if not db_path.exists():
        return [], []
    records: list[tuple[str, str, dict[str, Any]]] = []
    events: list[dict[str, Any]] = []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            conversations = conn.execute("SELECT * FROM conversations ORDER BY updated_at ASC").fetchall()
            chat_events = conn.execute(
                "SELECT * FROM chat_events ORDER BY conversation_id ASC, seq ASC"
            ).fetchall()
        except sqlite3.Error:
            return [], []
    for row in conversations:
        payload = {key: row[key] for key in row.keys()}
        payload["is_demo"] = bool(payload.get("is_demo"))
        records.append(("conversation", str(payload["conversation_id"]), _safe(payload)))
    for row in chat_events:
        payload = {key: row[key] for key in row.keys()}
        for key in ("mentions", "proof_refs", "artifact_refs", "metadata"):
            try:
                payload[key] = json.loads(payload[key] or ("{}" if key == "metadata" else "[]"))
            except (TypeError, ValueError):
                payload[key] = {} if key == "metadata" else []
        payload = _safe(payload)
        events.append(payload)
    return records, events


def collect(root: Path, chat_db: Path) -> tuple[list[tuple[str, str, dict[str, Any]]], list[dict[str, Any]]]:
    items: list[tuple[str, str, dict[str, Any]]] = []
    items.extend(_load_index(root, "captain/plans.json", "mission_plan"))
    items.extend(_load_json_records(root, "captain/state_machine", "captain_state"))
    items.extend(_load_json_records(root, "captain/runs", "captain_run"))
    items.extend(_load_json_records(root, "captain/issues", "captain_issue"))
    items.extend(_load_json_records(root, "board/tasks", "board_task"))
    items.extend(_load_json_records(root, "board/claims", "board_claim"))
    items.extend(_load_json_records(root, "projects", "project"))
    items.extend(_load_json_records(root, "runs", "workbench_run"))
    items.extend(_load_index(root, "runs/runs.json", "run"))
    items.extend(_load_index(root, "evidence/evidence.json", "evidence"))
    items.extend(_load_index(root, "gates/gates.json", "proof_gate"))
    for directory, record_type in (
        ("workbench/agents", "workbench_agent"),
        ("workbench/threads", "workbench_thread"),
        ("workbench/skills", "workbench_skill"),
        ("workbench/artifacts", "workbench_artifact"),
    ):
        items.extend(_load_json_records(root, directory, record_type))
    items.extend(_load_jsonl_records(root, "workbench/messages", "workbench_message"))
    conversations, events = _load_chat(chat_db)
    items.extend(conversations)
    return items, events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="inventory only (default)")
    mode.add_argument("--apply", action="store_true", help="write state to configured Cloud SQL")
    parser.add_argument("--root", type=Path, default=None, help="source Warden data root")
    parser.add_argument("--chat-db", type=Path, default=None, help="source group chat SQLite database")
    args = parser.parse_args()

    root = (args.root or data_root()).expanduser().resolve()
    chat_db = (args.chat_db or Path.home() / ".config" / "warden-brain" / "group_chat.sqlite").expanduser().resolve()
    items, events = collect(root, chat_db)
    by_type: dict[str, int] = {}
    for kind, _, _ in items:
        by_type[kind] = by_type.get(kind, 0) + 1
    report: dict[str, Any] = {
        "source_root": str(root),
        "chat_db": str(chat_db),
        "destination": "Cloud SQL via WARDEN_BRAIN_DATABASE_URL/DATABASE_URL" if args.apply else "not written (dry run)",
        "records": len(items),
        "records_by_type": dict(sorted(by_type.items())),
        "chat_events": len(events),
        "content_sha256": _digest(items),
        "secret_paths_excluded": ["connectors", "vault", ".env", "*.pem", "*token*", "*key*"],
        "failures": [],
    }
    if not args.apply:
        report["next_step"] = "Review this inventory, then rerun with --apply after Cloud SQL is reachable."
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    plane = CloudControlPlane()
    applied = 0
    try:
        plane.ensure_schema()
        applied = plane.upsert_records(items)
        event_batch = []
        for payload in events:
            event_id = str(payload.get("id") or payload.get("event_id"))
            idem = payload.get("idempotency_key") or f"migrate-chat:{event_id}"
            event_batch.append(
                (
                    str(payload.get("conversation_id") or "conv_warden_team"),
                    str(payload.get("event_type") or "human_message"),
                    payload,
                    event_id,
                    str(idem),
                )
            )
        report["applied_events"] = plane.append_events(event_batch)
    except Exception as exc:
        report["failures"].append({"error": str(exc), "after_records": applied})
    report["applied_records"] = applied
    report["status"] = "complete" if not report["failures"] else "partial"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
