"""Automatic wiki curation — the Marius model gateway (Ollama/OpenRouter/etc.)
reads promoted vault notes and distills them into wiki pages, unattended.

This is the piece that makes the raw -> wiki -> schema pattern (see wiki.py)
actually self-maintaining instead of requiring a human or a chat session to
call brain_distill_wiki by hand. It reuses Marius's existing
ProviderGateway (src/marius/provider_gateway.py) — the same local-first
Ollama-first, OpenRouter-fallback routing every other Warden agent call goes
through — so curation follows the same model policy as the rest of the
system rather than adding a second inference path.

Scope, deliberately: one source at a time (see Karpathy's own writeup —
batch distillation produces worse structure because nothing can guide what
gets emphasized), tight linking only against titles that already exist in
the wiki, and every source is looked up against wiki/*.md `source:`
frontmatter first so a source is never re-distilled once curated.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from .vault import get_vault_path, scan_sources
from .wiki import distill_note, list_wiki_pages

log = logging.getLogger(__name__)

# Folders worth distilling. 00-inbox is raw/unpromoted (see promote.py) and
# 90-archive is superseded content — neither belongs in the curated wiki.
DISTILLABLE_FOLDERS = {"10-projects", "20-people", "30-clients", "40-systems", "50-research", "60-daily"}

MIN_WORDS = 25
MAX_SOURCE_CHARS = 3500
MAX_EXISTING_TITLES = 60

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

DISTILL_TIMEOUT_SECONDS = 150
DISTILL_MAX_TOKENS = 700


class MariusModelClient:
    """Thin wrapper around Marius's ProviderGateway model *resolution*
    (Ollama-first, OpenRouter fallback — the same policy every other agent
    call in Warden respects) without the heavy per-call overhead
    ProviderGateway.chat() adds for interactive chat: grounding pack,
    "where left off" memory summary, and a persona system prompt. None of
    that is relevant to a structured-JSON distillation call, and in
    practice it was the difference between a ~50s and a >180s round trip
    on this hardware. Same provider, same model policy, a plain completion.
    """

    def __init__(self, gateway=None):
        from src.marius.provider_gateway import ProviderGateway
        self._gateway = gateway or ProviderGateway()

    async def chat(self, prompt: str, history=None, brain_enabled=None) -> dict:
        provider_name, model, profile, fallback_reason = await self._gateway.resolve_model_and_provider()

        if provider_name == "fallback":
            return {"response": "", "actual": "none", "error": fallback_reason or "no provider available"}

        provider = self._build_provider(provider_name, model)
        if provider is None:
            return {"response": "", "actual": "none", "error": f"unsupported provider: {provider_name}"}

        try:
            result = await provider.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=DISTILL_MAX_TOKENS,
            )
            content = result["choices"][0]["message"]["content"]
            return {"response": content, "actual": f"{provider_name}:{model}"}
        finally:
            if hasattr(provider, "cleanup"):
                await provider.cleanup()

    def _build_provider(self, provider_name: str, model: str):
        if provider_name == "ollama":
            from src.marius.providers.ollama import OllamaProvider
            return OllamaProvider(model, base_url=self._gateway.ollama_url, timeout=DISTILL_TIMEOUT_SECONDS)
        if provider_name == "openrouter":
            import os
            from src.marius.providers.openrouter import OpenRouterProvider
            return OpenRouterProvider(os.getenv("OPENROUTER_API_KEY"), model, timeout=DISTILL_TIMEOUT_SECONDS)
        return None


def _already_distilled_sources(vault_path: Path) -> set[str]:
    """Vault-relative source paths already referenced by a wiki page's
    `source:` frontmatter — never re-distill these."""
    seen: set[str] = set()
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.exists():
        return seen
    for p in wiki_dir.glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = re.search(r"^source:\s*(.+)$", text, re.MULTILINE)
        if m:
            seen.add(m.group(1).strip())
    return seen


def _candidate_sources(vault_path: Path, limit: int) -> list:
    already = _already_distilled_sources(vault_path)
    candidates = []
    for src in scan_sources(vault_path):
        top = src.path.split("/")[0] if "/" in src.path else ""
        if top not in DISTILLABLE_FOLDERS:
            continue
        if src.path in already:
            continue
        if src.path.endswith("/README.md"):
            continue
        if src.word_count < MIN_WORDS:
            continue
        candidates.append(src)
    return candidates[:limit]


def _build_prompt(source_title: str, source_body: str, existing_titles: list[str]) -> str:
    titles_block = "\n".join(f"- {t}" for t in existing_titles) or "(none yet — this is the first wiki page)"
    return f"""You are distilling a raw note into a wiki page for a personal second-brain knowledge base.

Read the note below fully, then respond with ONLY a single JSON object — no prose, no markdown fences — with these exact keys:
  "title": short, specific concept title (not just the filename)
  "definition": one to three sentences defining the concept in your own words
  "principles": array of 2-5 short bullet strings, the key takeaways
  "examples": array of 0-3 short concrete examples from the note (empty array if none)
  "tags": array of 1-4 lowercase kebab-case topic tags
  "links": array of titles FROM THE EXISTING WIKI TITLES LIST BELOW that this note genuinely relates to. Keep this tight — only include a link if understanding one page would meaningfully change how you understand the other. Empty array if nothing qualifies. Never invent a title that isn't in the list.

EXISTING WIKI TITLES:
{titles_block}

NOTE TITLE: {source_title}

NOTE CONTENT:
{source_body[:MAX_SOURCE_CHARS]}

Respond with only the JSON object.""".strip()


def _parse_llm_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).rstrip("`").strip()
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        raise ValueError("model response did not contain a JSON object")
    return json.loads(match.group(0))


async def curate_source(src, existing_titles: list[str], *, gateway=None, vault_path=None, index_path=None) -> dict:
    """Distill a single BrainSource into a wiki page via the model gateway."""
    if gateway is None:
        gateway = MariusModelClient()

    try:
        body = Path(src.abs_path).read_text(encoding="utf-8", errors="ignore") if src.abs_path else ""
    except OSError as exc:
        return {"ok": False, "path": src.path, "error": f"could not read source: {exc}"}

    prompt = _build_prompt(src.title, body, existing_titles)
    try:
        result = await gateway.chat(prompt, history=[], brain_enabled=False)
    except Exception as exc:
        detail = str(exc) or type(exc).__name__
        return {"ok": False, "path": src.path, "error": f"model gateway call failed: {detail}"}

    if isinstance(result, dict) and result.get("error") and not result.get("response"):
        return {"ok": False, "path": src.path, "error": f"model unavailable: {result['error']}"}

    raw_response = result.get("response", "") if isinstance(result, dict) else str(result)
    try:
        parsed = _parse_llm_json(raw_response)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "path": src.path, "error": f"could not parse model response as JSON: {exc}"}

    title = str(parsed.get("title") or src.title).strip()
    definition = str(parsed.get("definition") or "").strip()
    if not definition:
        return {"ok": False, "path": src.path, "error": "model returned an empty definition"}

    existing_lower = {t.strip().lower() for t in existing_titles}
    links = [l for l in (parsed.get("links") or []) if str(l).strip().lower() in existing_lower]

    try:
        page = distill_note(
            title=title,
            definition=definition,
            principles=parsed.get("principles") or [],
            examples=parsed.get("examples") or [],
            tags=parsed.get("tags") or [],
            links=links,
            source_path=src.path,
            vault_path=vault_path,
            index_path=index_path,
        )
    except ValueError as exc:
        return {"ok": False, "path": src.path, "error": str(exc)}

    page["ok"] = True
    page["source_path"] = src.path
    page["model"] = result.get("actual") or result.get("model") if isinstance(result, dict) else None
    return page


async def curate_vault(
    *,
    vault_path=None,
    index_path=None,
    limit: int = 5,
    dry_run: bool = False,
    gateway=None,
) -> dict:
    """Find un-distilled, promoted vault notes and turn each into a wiki page.

    One source at a time, sequentially — deliberately not parallelized, so
    each distillation can use the growing set of existing wiki titles for
    linking (a source distilled earlier in the same run is linkable by the
    next one).
    """
    vp = vault_path or get_vault_path()
    if not vp.exists():
        return {"ok": True, "scanned": 0, "distilled": [], "errors": []}

    candidates = _candidate_sources(vp, limit)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "scanned": len(candidates),
            "would_distill": [c.path for c in candidates],
        }

    distilled: list[dict] = []
    errors: list[dict] = []

    for src in candidates:
        existing_titles = [p["title"] for p in list_wiki_pages(vp)][:MAX_EXISTING_TITLES]
        result = await curate_source(src, existing_titles, gateway=gateway, vault_path=vp, index_path=index_path)
        if result.get("ok"):
            distilled.append(result)
        else:
            errors.append(result)

    return {
        "ok": True,
        "dry_run": False,
        "scanned": len(candidates),
        "distilled": distilled,
        "errors": errors,
    }
