"""Local Markdown vault brain provider — search and extractive answering."""
from __future__ import annotations

import logging
import re
from typing import Optional

from .index import fts_search, count_sources, reindex_sources, list_sources
from .models import BrainAnswer, BrainCitation
from .vault import scan_sources, get_vault_path, is_enabled

log = logging.getLogger(__name__)


def search(query: str, limit: int = 10, index_path=None) -> list[dict]:
    """FTS search over indexed Markdown vault. Returns list of result dicts."""
    chunks = fts_search(query, limit=limit, index_path=index_path)
    return [
        {
            "chunk_id": c.chunk_id,
            "source_id": c.source_id,
            "source_path": c.source_path,
            "title": c.title,
            "heading": c.heading,
            "excerpt": c.text[:400],
            "provider": "local",
        }
        for c in chunks
    ]


_STOP_WORDS = {
    "what", "is", "the", "a", "an", "of", "in", "for", "to", "and", "or",
    "how", "why", "when", "where", "who", "which", "are", "was", "were",
    "do", "does", "did", "has", "have", "had", "be", "been", "being",
    "can", "could", "will", "would", "should", "may", "might", "shall",
    "at", "by", "from", "with", "about", "into", "through", "during",
    "my", "your", "their", "this", "that", "these", "those", "its",
}


def _keywords(text: str) -> str:
    """Extract content keywords from a question, dropping stop words."""
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    kw = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
    return " ".join(kw) if kw else text


def answer(question: str, limit: int = 6, index_path=None, vault_path=None) -> BrainAnswer:
    """Extractive answer: search chunks and compose an answer with citations."""
    # Try full question first, fall back to keywords for FTS5
    chunks = fts_search(question, limit=limit, index_path=index_path)
    if not chunks:
        chunks = fts_search(_keywords(question), limit=limit, index_path=index_path)

    if not chunks:
        return BrainAnswer(
            answer="No relevant sources found in the local vault for that question.",
            confidence=0.0,
            provider_used="local",
            local_count=0,
            recommended_next_action="Add relevant notes to your vault and reindex.",
        )

    # Build extractive answer from top chunks
    seen_sources: set[str] = set()
    citations: list[BrainCitation] = []
    answer_parts: list[str] = []

    for chunk in chunks:
        excerpt = chunk.text[:300].strip()
        answer_parts.append(excerpt)
        if chunk.source_id not in seen_sources:
            seen_sources.add(chunk.source_id)
            citations.append(BrainCitation(
                source_path=chunk.source_path,
                title=chunk.title,
                heading=chunk.heading,
                excerpt=chunk.text[:200],
                provider="local",
                score=1.0,
            ))

    answer_text = "\n\n".join(answer_parts[:3])
    confidence = min(0.9, 0.3 * len(citations))

    return BrainAnswer(
        answer=answer_text,
        citations=citations,
        confidence=confidence,
        provider_used="local",
        local_count=len(chunks),
        recommended_next_action="Review the cited sources for full context.",
    )


def reindex(vault_path=None, index_path=None, force: bool = False) -> dict:
    """Scan vault and reindex all sources."""
    vp = vault_path or get_vault_path()
    sources = scan_sources(vp)
    result = reindex_sources(sources, index_path=index_path, force=force)
    result["source_count"] = len(sources)
    result["vault_path"] = str(vp)
    return result


def status(vault_path=None, index_path=None) -> dict:
    vp = vault_path or get_vault_path()
    return {
        "provider": "local",
        "enabled": is_enabled(),
        "vault_path": str(vp),
        "vault_exists": vp.exists(),
        "source_count": count_sources(index_path=index_path),
        "sources": list_sources(index_path=index_path, limit=5),
    }
