"""Hybrid brain answering — parallel local + Google fanout with merge.

If Google is disabled: local only.
If Google is enabled+configured: query both in parallel, merge, dedup.
If Google fails: fall back gracefully, include error in trace.
Never fail the whole answer because Google is unavailable.
"""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Optional

from .models import BrainAnswer, BrainCitation
from . import local_provider, google_provider

log = logging.getLogger(__name__)


def _dedup_citations(citations: list[BrainCitation]) -> list[BrainCitation]:
    """Remove duplicates by (title, heading) keeping first occurrence."""
    seen: set[tuple] = set()
    out: list[BrainCitation] = []
    for c in citations:
        key = (c.title.lower().strip(), c.heading.lower().strip())
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def search(query: str, limit: int = 10, index_path=None) -> list[dict]:
    """Parallel search — local + Google (if enabled). Merge by score."""
    local_results = local_provider.search(query, limit=limit, index_path=index_path)

    if not google_provider.is_enabled():
        return local_results

    google_results: list[dict] = []
    try:
        google_results = google_provider.search(query, limit=limit)
        # Filter out errors
        errors = [r for r in google_results if "error" in r]
        google_results = [r for r in google_results if "error" not in r]
        if errors:
            log.warning("Google brain search errors: %s", errors)
    except Exception as exc:
        log.warning("Google brain search exception: %s", exc)

    # Merge: interleave (round-robin by provider)
    merged: list[dict] = []
    i = j = 0
    while i < len(local_results) and j < len(google_results):
        merged.append(local_results[i]); i += 1
        merged.append(google_results[j]); j += 1
    merged.extend(local_results[i:])
    merged.extend(google_results[j:])
    return merged[:limit * 2]


def answer(
    question: str,
    limit: int = 6,
    index_path=None,
    vault_path=None,
) -> BrainAnswer:
    """Hybrid answer with parallel fanout. Returns merged BrainAnswer."""
    use_google = google_provider.is_enabled() and google_provider.is_configured()

    if not use_google:
        result = local_provider.answer(question, limit=limit, index_path=index_path, vault_path=vault_path)
        return result

    # Parallel fanout
    local_ans: Optional[BrainAnswer] = None
    google_ans: Optional[BrainAnswer] = None
    google_error: Optional[str] = None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        local_fut = pool.submit(local_provider.answer, question, limit, index_path, vault_path)
        google_fut = pool.submit(google_provider.answer, question, limit)

        try:
            local_ans = local_fut.result(timeout=15)
        except Exception as exc:
            log.warning("Local brain answer failed: %s", exc)
            local_ans = BrainAnswer(answer="", provider_used="local", errors=[str(exc)])

        try:
            google_ans = google_fut.result(timeout=30)
        except Exception as exc:
            google_error = str(exc)
            log.warning("Google brain answer failed: %s", exc)
            google_ans = BrainAnswer(answer="", provider_used="google_discovery_engine", errors=[str(exc)])

    # Merge
    all_citations = (local_ans.citations or []) + (google_ans.citations or [])
    deduped = _dedup_citations(all_citations)
    all_errors = (local_ans.errors or []) + (google_ans.errors or [])
    if google_error:
        all_errors.append(f"Google Brain failed: {google_error}")

    # Compose combined answer
    parts = []
    if local_ans.answer and local_ans.answer != "No relevant sources found in the local vault for that question.":
        parts.append(f"**From local vault:**\n{local_ans.answer}")
    if google_ans.answer and "not enabled" not in google_ans.answer and "no results" not in google_ans.answer.lower():
        parts.append(f"**From Google Brain:**\n{google_ans.answer}")

    if not parts:
        combined = local_ans.answer or "No relevant sources found."
    else:
        combined = "\n\n".join(parts)

    local_count = local_ans.local_count or 0
    google_count = google_ans.google_count or 0
    provider_used = (
        "hybrid" if (local_count > 0 and google_count > 0)
        else "google" if google_count > 0
        else "local"
    )

    return BrainAnswer(
        answer=combined,
        citations=deduped,
        confidence=max(local_ans.confidence, google_ans.confidence),
        provider_used=provider_used,
        local_count=local_count,
        google_count=google_count,
        errors=all_errors,
        unresolved_questions=local_ans.unresolved_questions + google_ans.unresolved_questions,
        recommended_next_action=local_ans.recommended_next_action or google_ans.recommended_next_action,
    )
