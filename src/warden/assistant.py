from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .rag_adapters import GOOGLE_RAG_ADAPTER
from .workbench import WorkbenchStore, redact_memory_text

ALLOWLISTED_PROJECT_DOCS = (
    "README.md",
    "CLAUDE.md",
    "docs/warden_memory.md",
    "docs/warden_memory_style.md",
    "docs/warden_memory_examples.md",
    "docs/warden_assistant.md",
)


class AssistantRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=160)
    repo_path: Optional[str] = Field(default=None, max_length=500)
    message: str = Field(min_length=1, max_length=20_000)
    include_memory: bool = True
    include_project_context: bool = True
    include_google_rag: bool = False
    max_memories: int = Field(default=5, ge=1, le=20)
    max_chars: int = Field(default=4000, ge=256, le=12_000)


class AssistantSource(BaseModel):
    kind: str
    title: str
    ref: str
    excerpt: Optional[str] = None


class AssistantResponse(BaseModel):
    ok: bool = True
    answer: str
    sources: list[AssistantSource] = Field(default_factory=list)
    memory_ids: list[str] = Field(default_factory=list)
    context_used: dict[str, Any] = Field(default_factory=dict)
    provider: str = "local-deterministic"
    warnings: list[str] = Field(default_factory=list)


def assistant_health_payload() -> dict[str, Any]:
    rag = GOOGLE_RAG_ADAPTER.status_payload()
    return {
        "ok": True,
        "private_only": True,
        "provider": "local-deterministic",
        "google_rag": rag,
        "allowlisted_docs": list(ALLOWLISTED_PROJECT_DOCS),
    }


def _resolve_repo_root(repo_path: Optional[str], allowed_repo_roots: list[Path]) -> tuple[Optional[Path], list[str]]:
    warnings: list[str] = []
    if not repo_path:
        return None, warnings
    try:
        resolved = Path(repo_path).expanduser().resolve()
    except Exception:
        warnings.append("Repo path could not be resolved, so project docs were skipped.")
        return None, warnings
    allowed: list[Path] = []
    for root in allowed_repo_roots:
        try:
            allowed.append(root.resolve())
        except Exception:
            continue
    if resolved not in allowed:
        warnings.append("Repo path is not allowlisted for assistant doc reads, so project docs were skipped.")
        return None, warnings
    return resolved, warnings


def _read_allowlisted_docs(repo_root: Optional[Path], max_chars: int) -> tuple[list[dict[str, str]], list[str]]:
    if repo_root is None:
        return [], []
    docs: list[dict[str, str]] = []
    warnings: list[str] = []
    remaining = max(600, min(max_chars, 8000))
    for relative_path in ALLOWLISTED_PROJECT_DOCS:
        target = repo_root / relative_path
        if not target.exists() or not target.is_file():
            continue
        try:
            raw = target.read_text(encoding="utf-8")
        except Exception:
            warnings.append(f"Could not read {relative_path}.")
            continue
        excerpt = (redact_memory_text(raw) or "").strip()
        if not excerpt:
            continue
        excerpt = excerpt[: min(remaining, 1200)]
        docs.append({"path": relative_path, "title": target.name, "content": excerpt})
        remaining -= len(excerpt)
        if remaining <= 0:
            break
    return docs, warnings


def build_assistant_context(
    payload: AssistantRequest,
    store: WorkbenchStore,
    allowed_repo_roots: list[Path],
) -> dict[str, Any]:
    warnings: list[str] = []
    sources: list[AssistantSource] = []
    memory_pack = {
        "context": "",
        "memory_count": 0,
        "memory_ids": [],
        "truncated": False,
        "scope": payload.project_id,
    }
    if payload.include_memory:
        try:
            memory_pack = store.build_memory_context_pack(
                project_id=payload.project_id,
                repo_path=payload.repo_path,
                user_prompt=payload.message,
                max_memories=payload.max_memories,
                max_chars=min(payload.max_chars, 6000),
            )
        except Exception:
            warnings.append("Memory context is unavailable, so the assistant answered without it.")
    repo_root, repo_warnings = _resolve_repo_root(payload.repo_path, allowed_repo_roots)
    warnings.extend(repo_warnings)
    project_docs: list[dict[str, str]] = []
    if payload.include_project_context:
        project_docs, doc_warnings = _read_allowlisted_docs(repo_root, payload.max_chars)
        warnings.extend(doc_warnings)
    for memory_id in memory_pack["memory_ids"]:
        sources.append(AssistantSource(kind="memory", title=memory_id, ref=f"memory:{memory_id}"))
    for doc in project_docs:
        sources.append(
            AssistantSource(
                kind="project_doc",
                title=doc["title"],
                ref=f"doc:{doc['path']}",
                excerpt=doc["content"][:220],
            )
        )
    google_rag = GOOGLE_RAG_ADAPTER.fetch_context(payload.message, max_chars=payload.max_chars)
    if payload.include_google_rag and google_rag.get("warning"):
        warnings.append(str(google_rag["warning"]))
    return {
        "ok": True,
        "memory_context": memory_pack,
        "project_docs": project_docs,
        "sources": [source.model_dump(mode="json") for source in sources],
        "warnings": warnings,
        "context_used": {
            "memory": {
                "included": payload.include_memory,
                "memory_count": memory_pack["memory_count"],
                "truncated": memory_pack["truncated"],
            },
            "project_docs": {
                "included": payload.include_project_context,
                "doc_count": len(project_docs),
                "paths": [doc["path"] for doc in project_docs],
            },
            "google_rag": {
                "requested": payload.include_google_rag,
                "enabled": bool(google_rag.get("enabled")),
            },
        },
        "provider": "local-deterministic",
    }


def _extract_doc_highlights(project_docs: list[dict[str, str]]) -> list[str]:
    highlights: list[str] = []
    for doc in project_docs[:3]:
        line = next((row.strip() for row in doc["content"].splitlines() if row.strip()), "")
        if line:
            highlights.append(f"{doc['path']}: {line[:140]}")
    return highlights


def chat_with_assistant(
    payload: AssistantRequest,
    store: WorkbenchStore,
    allowed_repo_roots: list[Path],
) -> AssistantResponse:
    context = build_assistant_context(payload, store, allowed_repo_roots)
    memory_context = context["memory_context"]
    project_docs = context["project_docs"]
    warnings = list(context["warnings"])
    message_lower = payload.message.lower()
    answer_lines = ["Warden Assistant reviewed local, allowlisted context only."]
    if memory_context["memory_count"]:
        answer_lines.append(
            f"I found {memory_context['memory_count']} relevant memory record"
            f"{'' if memory_context['memory_count'] == 1 else 's'} for this project."
        )
    if project_docs:
        answer_lines.append(
            f"I also checked {len(project_docs)} allowlisted project document"
            f"{'' if len(project_docs) == 1 else 's'}."
        )
    if "memory" in message_lower:
        answer_lines.append("Warden Memory is project-scoped and private-runner-only, with redaction on write and render.")
    if "google" in message_lower or "rag" in message_lower:
        answer_lines.append("Google RAG is present only as a disabled-by-default adapter slot in this build.")
    if "assistant" in message_lower:
        answer_lines.append("This assistant stays local, reads allowlisted docs only, and falls back to deterministic answers when no LLM is configured.")
    doc_highlights = _extract_doc_highlights(project_docs)
    if doc_highlights:
        answer_lines.append("Relevant project context:")
        answer_lines.extend(f"- {highlight}" for highlight in doc_highlights[:3])
    if memory_context["context"]:
        answer_lines.append("Memory context is attached as evidence-backed operator context, not as arbitrary filesystem crawl.")
    if not memory_context["memory_count"] and not project_docs:
        answer_lines.append("I do not have enough local Warden context to answer that confidently yet.")
    answer = redact_memory_text("\n".join(answer_lines).strip()) or "Warden Assistant could not build a safe answer."
    return AssistantResponse(
        answer=answer,
        sources=[AssistantSource(**source) for source in context["sources"]],
        memory_ids=list(memory_context["memory_ids"]),
        context_used=context["context_used"],
        provider=str(context["provider"]),
        warnings=warnings,
    )
