"""Persistent Warden run history and evidence records."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

_FILE_LOCK = threading.Lock()

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-or-[A-Za-z0-9._-]{8,}"), "sk-or-[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "sk-[REDACTED]"),
    (
        re.compile(r"(?i)\b(api[_-]?key|token|password|secret|authorization)\b\s*[:=]\s*\S+"),
        r"\1: [REDACTED]",
    ),
    (
        re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"),
        "[REDACTED PRIVATE KEY]",
    ),
]

ENV_FILE_MARKERS = (
    "OPENROUTER_API_KEY=",
    "MCHARNESS_ADMIN_TOKEN=",
    "JULES_API_KEY=",
    "AWS_SECRET_ACCESS_KEY=",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def runs_index_path(root: Path) -> Path:
    return root / "runs" / "runs.json"


def evidence_index_path(root: Path) -> Path:
    return root / "evidence" / "evidence.json"


def evidence_item_dir(root: Path) -> Path:
    return root / "evidence" / "items"


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read storage index: {path.name}") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail=f"Invalid storage index format: {path.name}")
    return data


def _write_json_list(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def redact_secrets(text: str) -> tuple[str, bool]:
    if not text:
        return "", False
    redacted = False
    out = text
    for pattern, replacement in SECRET_PATTERNS:
        new_out, count = pattern.subn(replacement, out)
        if count:
            redacted = True
            out = new_out
    return out, redacted


def _reject_env_like_content(text: str) -> None:
    if not text:
        return
    lowered = text.lower()
    if ".env" in lowered and any(marker.lower() in lowered for marker in ENV_FILE_MARKERS):
        raise HTTPException(status_code=400, detail="Refusing to store env-file style secret content.")
    if sum(1 for marker in ENV_FILE_MARKERS if marker in text) >= 2:
        raise HTTPException(status_code=400, detail="Refusing to store multi-secret env content.")


def _derive_run_title(title: str | None, prompt: str | None) -> str:
    if title and title.strip():
        return title.strip()[:120]
    if prompt and prompt.strip():
        first = prompt.strip().splitlines()[0].strip()
        if first:
            return first[:120]
    return "Codex run"


def _prompt_excerpt(prompt: str, limit: int = 400) -> str:
    text = (prompt or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _content_excerpt(text: str, limit: int = 600) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def create_run_record(
    root: Path,
    *,
    run_id: str,
    title: str | None,
    agent_id: str,
    agent_adapter: str,
    repo_id: str,
    branch: str | None,
    prompt: str,
    status: str,
    session_id: str | None = None,
    plan_id: str | None = None,
    transcript_path: str | None = None,
    transcript_excerpt: str | None = None,
    created_by: str = "operator",
    service_mode: str = "private",
    original_prompt: str | None = None,
) -> dict[str, Any]:
    safe_prompt, prompt_redacted = redact_secrets(prompt or "")
    _reject_env_like_content(safe_prompt)
    safe_transcript, transcript_redacted = redact_secrets(transcript_excerpt or "")
    safe_original, _ = redact_secrets(original_prompt or "") if original_prompt else ("", False)
    record = {
        "run_id": run_id,
        "title": _derive_run_title(title, safe_original or safe_prompt),
        "agent_id": agent_id,
        "agent_adapter": agent_adapter,
        "repo_id": repo_id,
        "branch": branch,
        "prompt": safe_prompt,
        "original_prompt": safe_original or None,
        "status": status,
        "started_at": _now_iso(),
        "completed_at": None,
        "transcript_excerpt": safe_transcript,
        "transcript_path": transcript_path,
        "evidence_ids": [],
        "created_by": created_by,
        "service_mode": service_mode,
        "session_id": session_id,
        "plan_id": plan_id,
        "redacted": prompt_redacted or transcript_redacted,
    }
    with _FILE_LOCK:
        path = runs_index_path(root)
        rows = _read_json_list(path)
        rows = [row for row in rows if row.get("run_id") != run_id]
        rows.insert(0, record)
        _write_json_list(path, rows[:200])
    return sanitize_run_summary(record)


def update_run_record(root: Path, run_id: str, **fields: Any) -> dict[str, Any] | None:
    with _FILE_LOCK:
        path = runs_index_path(root)
        rows = _read_json_list(path)
        updated: dict[str, Any] | None = None
        for index, row in enumerate(rows):
            if row.get("run_id") != run_id:
                continue
            merged = dict(row)
            for key, value in fields.items():
                if value is None and key not in {"completed_at", "transcript_excerpt", "transcript_path", "branch"}:
                    continue
                if key in {"prompt", "transcript_excerpt"} and isinstance(value, str):
                    safe_value, redacted = redact_secrets(value)
                    _reject_env_like_content(safe_value)
                    merged[key] = safe_value
                    if redacted:
                        merged["redacted"] = True
                else:
                    merged[key] = value
            rows[index] = merged
            updated = merged
            break
        if updated is None:
            return None
        _write_json_list(path, rows)
    return sanitize_run_summary(updated)


def get_run_record(root: Path, run_id: str) -> dict[str, Any] | None:
    with _FILE_LOCK:
        rows = _read_json_list(runs_index_path(root))
    for row in rows:
        if row.get("run_id") == run_id:
            return sanitize_run_detail(row)
    return None


def list_recent_runs(root: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    with _FILE_LOCK:
        rows = _read_json_list(runs_index_path(root))
    return [sanitize_run_summary(row) for row in rows[:limit]]


def find_run_by_session(root: Path, session_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    with _FILE_LOCK:
        rows = _read_json_list(runs_index_path(root))
    for row in rows:
        if row.get("session_id") == session_id:
            return row
    return None


def create_evidence_record(
    root: Path,
    *,
    run_id: str | None,
    evidence_type: str,
    title: str,
    summary: str | None = None,
    content: str | None = None,
    content_excerpt: str | None = None,
    agent_id: str | None = None,
    source: str = "operator",
) -> dict[str, Any]:
    body = content or content_excerpt or summary or ""
    _reject_env_like_content(body)
    safe_body, redacted = redact_secrets(body)
    safe_summary, summary_redacted = redact_secrets(summary or "")
    if summary_redacted:
        redacted = True
    excerpt = _content_excerpt(content_excerpt or safe_body)
    evidence_id = f"ev_{uuid.uuid4().hex[:10]}"
    item_path = evidence_item_dir(root) / f"{evidence_id}.txt"
    item_path.parent.mkdir(parents=True, exist_ok=True)
    item_path.write_text(safe_body, encoding="utf-8")
    record = {
        "evidence_id": evidence_id,
        "run_id": run_id,
        "type": evidence_type,
        "title": title[:160],
        "summary": safe_summary[:400] if safe_summary else _content_excerpt(safe_body, 240),
        "content_path": str(item_path),
        "content_excerpt": excerpt,
        "created_at": _now_iso(),
        "agent_id": agent_id,
        "source": source,
        "redacted": redacted,
    }
    with _FILE_LOCK:
        index_path = evidence_index_path(root)
        rows = _read_json_list(index_path)
        rows.insert(0, record)
        _write_json_list(index_path, rows[:500])
        if run_id:
            runs_path = runs_index_path(root)
            run_rows = _read_json_list(runs_path)
            for index, row in enumerate(run_rows):
                if row.get("run_id") != run_id:
                    continue
                evidence_ids = list(row.get("evidence_ids") or [])
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
                run_rows[index]["evidence_ids"] = evidence_ids
                break
            _write_json_list(runs_path, run_rows)
    return sanitize_evidence_summary(record)


def get_evidence_record(root: Path, evidence_id: str) -> dict[str, Any] | None:
    with _FILE_LOCK:
        rows = _read_json_list(evidence_index_path(root))
    for row in rows:
        if row.get("evidence_id") == evidence_id:
            detail = dict(row)
            content_path = row.get("content_path")
            if content_path:
                path = Path(content_path)
                if path.exists():
                    text, _ = redact_secrets(path.read_text(encoding="utf-8"))
                    detail["content"] = text
            return sanitize_evidence_detail(detail)
    return None


def list_recent_evidence(root: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    with _FILE_LOCK:
        rows = _read_json_list(evidence_index_path(root))
    return [sanitize_evidence_summary(row) for row in rows[:limit]]


def evidence_summaries_for_run(root: Path, evidence_ids: list[str]) -> list[dict[str, Any]]:
    if not evidence_ids:
        return []
    with _FILE_LOCK:
        rows = _read_json_list(evidence_index_path(root))
    by_id = {row.get("evidence_id"): row for row in rows}
    out: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        row = by_id.get(evidence_id)
        if row:
            out.append(sanitize_evidence_summary(row))
    return out


def sanitize_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    prompt = run.get("prompt") or ""
    excerpt_source = run.get("original_prompt") or prompt
    transcript = run.get("transcript_excerpt") or ""
    return {
        "run_id": run.get("run_id"),
        "title": run.get("title"),
        "agent_id": run.get("agent_id"),
        "agent_adapter": run.get("agent_adapter"),
        "repo_id": run.get("repo_id"),
        "branch": run.get("branch"),
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "prompt_excerpt": _prompt_excerpt(excerpt_source),
        "transcript_excerpt": _content_excerpt(transcript, 500),
        "evidence_count": len(run.get("evidence_ids") or []),
        "evidence_ids": list(run.get("evidence_ids") or []),
        "created_by": run.get("created_by"),
        "service_mode": run.get("service_mode"),
        "plan_id": run.get("plan_id"),
        "redacted": bool(run.get("redacted")),
    }


def sanitize_run_detail(run: dict[str, Any]) -> dict[str, Any]:
    summary = sanitize_run_summary(run)
    summary["session_id"] = run.get("session_id")
    summary["transcript_path"] = run.get("transcript_path")
    summary["prompt"] = _prompt_excerpt(run.get("prompt") or "", 1200)
    return summary


def sanitize_evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": evidence.get("evidence_id"),
        "run_id": evidence.get("run_id"),
        "type": evidence.get("type"),
        "title": evidence.get("title"),
        "summary": evidence.get("summary"),
        "content_excerpt": evidence.get("content_excerpt"),
        "created_at": evidence.get("created_at"),
        "agent_id": evidence.get("agent_id"),
        "source": evidence.get("source"),
        "redacted": bool(evidence.get("redacted")),
    }


def sanitize_evidence_detail(evidence: dict[str, Any]) -> dict[str, Any]:
    detail = sanitize_evidence_summary(evidence)
    content = evidence.get("content")
    if isinstance(content, str):
        detail["content"] = _content_excerpt(content, 8000)
    return detail