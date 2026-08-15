#!/usr/bin/env python3
"""Recover deleted Workbench memories from local agent session receipts.

The vector index proves which Workbench memory IDs existed, but it does not
store their text.  Codex and Claude session logs often retain both the
``warden_remember`` arguments and the returned memory ID.  This script joins
those receipts without guessing.  It writes a recovery candidate directory;
it never edits the live Workbench directory.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


RECOVERY_SOURCE = "recovered-session-log"


def _jsonl_rows(root: Path) -> Iterator[tuple[Path, int, dict[str, Any]]]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*.jsonl")):
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, 1):
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        yield path, line_number, row
        except OSError:
            continue


def _decoded_json_values(text: str) -> Iterator[Any]:
    if "memory_id" not in text:
        return
    decoder = json.JSONDecoder()
    cursor = 0
    while cursor < len(text):
        starts = [index for index in (text.find("{", cursor), text.find("[", cursor)) if index >= 0]
        if not starts:
            break
        start = min(starts)
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        yield value
        cursor = max(end, start + 1)


def _walk_values(value: Any, *, depth: int = 0) -> Iterator[Any]:
    if depth > 8:
        return
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk_values(nested, depth=depth + 1)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_values(nested, depth=depth + 1)
    elif isinstance(value, str):
        for decoded in _decoded_json_values(value):
            yield from _walk_values(decoded, depth=depth + 1)


def _memory_ids(value: Any, allowed_ids: set[str]) -> set[str]:
    return {
        memory_id
        for item in _walk_values(value)
        if isinstance(item, dict)
        and isinstance((memory_id := item.get("memory_id")), str)
        and memory_id in allowed_ids
    }


def _vector_records(vector_db: Path) -> dict[str, dict[str, Any]]:
    with sqlite3.connect(vector_db) as connection:
        rows = connection.execute(
            "select memory_id, meta from brain_vectors where memory_id like 'm-%' order by memory_id"
        ).fetchall()
    records: dict[str, dict[str, Any]] = {}
    for memory_id, raw_meta in rows:
        try:
            meta = json.loads(raw_meta or "{}")
        except json.JSONDecodeError:
            meta = {}
        records[str(memory_id)] = meta if isinstance(meta, dict) else {}
    return records


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result: list[str] = []
    for item in values:
        tag = str(item).strip()
        if tag and tag not in result:
            result.append(tag)
    return result


def _timestamp(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return datetime.now(timezone.utc).isoformat()


def _kind(value: Any, fallback: str = "user_note") -> str:
    raw = str(value or fallback).strip().lower()
    return "user_note" if raw == "note" else raw


def _exact_record(
    memory_id: str,
    arguments: dict[str, Any],
    *,
    timestamp: str,
    path: Path,
    line_number: int,
    client: str,
    vector_meta: dict[str, Any],
) -> dict[str, Any] | None:
    summary = str(arguments.get("text") or arguments.get("content") or "").strip()
    if not summary:
        return None
    project = str(
        arguments.get("project")
        or arguments.get("project_id")
        or vector_meta.get("project")
        or "warden"
    ).strip()
    tags = _tags(arguments.get("tags"))
    for tag in ("recovered", "recovery-exact"):
        if tag not in tags:
            tags.append(tag)
    source_ref = f"session-log:{client}:{path.name}:{line_number}"
    return {
        "memory_id": memory_id,
        "scope": project,
        "summary": summary,
        "source": RECOVERY_SOURCE,
        "title": str(arguments.get("title") or summary[:80]).strip(),
        "source_ref": source_ref,
        "tags": tags,
        "kind": _kind(arguments.get("kind"), str(vector_meta.get("kind") or "user_note")),
        "status": "active",
        # Recovery fidelity is recorded in metadata. Do not reinterpret it as
        # confidence in the truth of the original agent-authored claim.
        "confidence": None,
        "project_id": project,
        "repo_path": None,
        "branch": None,
        "task_id": None,
        "agent_id": f"recovered-{client}",
        "metadata": {
            "recovery_quality": "exact_tool_call",
            "recovery_source": source_ref,
            "recovered_from_client": client,
        },
        "compacted": False,
        "notes": "Recovered from a successful warden_remember call and its returned memory ID.",
        "raw_content": None,
        "raw_content_truncated": False,
        "created_at": _timestamp(timestamp),
        "updated_at": _timestamp(timestamp),
    }


def _codex_exact(
    root: Path,
    vector_records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    recovered: dict[str, dict[str, Any]] = {}
    allowed_ids = set(vector_records)
    for path, line_number, row in _jsonl_rows(root):
        if "warden_remember" not in json.dumps(row, separators=(",", ":")):
            continue
        payload = row.get("payload") or {}
        if payload.get("type") != "mcp_tool_call_end":
            continue
        invocation = payload.get("invocation") or {}
        if not str(invocation.get("tool", "")).endswith("warden_remember"):
            continue
        arguments = invocation.get("arguments") or {}
        if not isinstance(arguments, dict):
            continue
        for memory_id in _memory_ids(payload.get("result"), allowed_ids):
            record = _exact_record(
                memory_id,
                arguments,
                timestamp=str(row.get("timestamp") or ""),
                path=path,
                line_number=line_number,
                client="codex",
                vector_meta=vector_records[memory_id],
            )
            if record:
                recovered[memory_id] = record
    return recovered


def _claude_exact(
    root: Path,
    vector_records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    recovered: dict[str, dict[str, Any]] = {}
    allowed_ids = set(vector_records)
    pending: dict[str, tuple[dict[str, Any], str, Path, int]] = {}
    for path, line_number, row in _jsonl_rows(root):
        message = row.get("message") or {}
        content = message.get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and str(block.get("name", "")).endswith("warden_remember"):
                arguments = block.get("input") or {}
                if isinstance(arguments, dict) and isinstance(block.get("id"), str):
                    pending[block["id"]] = (
                        arguments,
                        str(row.get("timestamp") or ""),
                        path,
                        line_number,
                    )
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in pending:
                arguments, timestamp, call_path, call_line = pending.pop(block["tool_use_id"])
                for memory_id in _memory_ids(block.get("content"), allowed_ids):
                    record = _exact_record(
                        memory_id,
                        arguments,
                        timestamp=timestamp,
                        path=call_path,
                        line_number=call_line,
                        client="claude",
                        vector_meta=vector_records[memory_id],
                    )
                    if record:
                        recovered[memory_id] = record
    return recovered


def _partial_candidates(
    roots: Iterable[Path],
    vector_records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    allowed_ids = set(vector_records)
    best: dict[str, tuple[tuple[int, int], dict[str, Any], str]] = {}
    for root in roots:
        for path, line_number, row in _jsonl_rows(root):
            if "memory_id" not in json.dumps(row, separators=(",", ":")):
                continue
            for item in _walk_values(row):
                if not isinstance(item, dict):
                    continue
                memory_id = item.get("memory_id")
                summary = item.get("summary")
                if memory_id not in allowed_ids or not isinstance(summary, str) or not summary.strip():
                    continue
                useful = {
                    key: item.get(key)
                    for key in ("title", "summary", "kind", "project", "project_id", "tags", "updated_at")
                    if item.get(key) is not None
                }
                score = (len(summary.strip()), len(useful))
                source_ref = f"session-log:partial:{path.name}:{line_number}"
                if memory_id not in best or score > best[memory_id][0]:
                    best[memory_id] = (score, useful, source_ref)

    recovered: dict[str, dict[str, Any]] = {}
    for memory_id, (_, item, source_ref) in best.items():
        summary = str(item["summary"]).strip()
        vector_meta = vector_records[memory_id]
        project = str(item.get("project") or item.get("project_id") or vector_meta.get("project") or "warden")
        timestamp = _timestamp(item.get("updated_at"))
        tags = _tags(item.get("tags"))
        for tag in ("recovered", "recovery-partial"):
            if tag not in tags:
                tags.append(tag)
        recovered[memory_id] = {
            "memory_id": memory_id,
            "scope": project,
            "summary": summary + " [Recovered summary; the original record may have contained additional text.]",
            "source": RECOVERY_SOURCE,
            "title": str(item.get("title") or summary[:80]).strip(),
            "source_ref": source_ref,
            "tags": tags,
            "kind": _kind(item.get("kind"), str(vector_meta.get("kind") or "user_note")),
            "status": "active",
            "confidence": None,
            "project_id": project,
            "repo_path": None,
            "branch": None,
            "task_id": None,
            "agent_id": "recovered-session-summary",
            "metadata": {
                "recovery_quality": "partial_summary",
                "recovery_source": source_ref,
                "original_summary_length": len(summary),
            },
            "compacted": True,
            "notes": "Recovered from a prior recall result. Original full text was not available.",
            "raw_content": None,
            "raw_content_truncated": True,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    return recovered


def recover(
    *,
    vector_db: Path,
    codex_root: Path,
    claude_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    vector_records = _vector_records(vector_db)
    exact = _claude_exact(claude_root, vector_records)
    exact.update(_codex_exact(codex_root, vector_records))
    partial = _partial_candidates((codex_root, claude_root), vector_records)
    recovered = dict(partial)
    recovered.update(exact)
    unresolved = [
        {"memory_id": memory_id, "vector_meta": vector_records[memory_id]}
        for memory_id in sorted(set(vector_records) - set(recovered))
    ]
    manifest = {
        "schema": "warden.workbench.memory-recovery.v1",
        "vector_memory_count": len(vector_records),
        "exact_count": len(exact),
        "partial_count": len(set(partial) - set(exact)),
        "recovered_count": len(recovered),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
        "note": "Unresolved IDs are preserved as evidence only; no memory text was invented for them.",
    }
    return recovered, manifest


def _write_recovery(output: Path, recovered: dict[str, dict[str, Any]], manifest: dict[str, Any]) -> None:
    memory_root = output / "memories"
    memory_root.mkdir(parents=True, exist_ok=True)
    for memory_id, record in sorted(recovered.items()):
        (memory_root / f"{memory_id}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-db", type=Path, required=True)
    parser.add_argument("--codex-root", type=Path, default=Path.home() / ".codex" / "sessions")
    parser.add_argument("--claude-root", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    recovered, manifest = recover(
        vector_db=args.vector_db,
        codex_root=args.codex_root,
        claude_root=args.claude_root,
    )
    _write_recovery(args.output, recovered, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
