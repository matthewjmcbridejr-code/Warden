"""Wiki distillation layer — the Karpathy/"second brain" raw -> wiki -> schema
pattern, adapted to Warden's existing vault + SQLite FTS5 stack.

The pattern (see Karpathy's LLM Wiki gist, and the Obsidian+Claude Code
write-ups it inspired): raw captured material is never "the knowledge" — it's
ingredient material. A wiki page is a standalone, human-curated concept: a
one-line definition, key principles, examples, and a short, *deliberately
chosen* set of [[links]] to other pages. The graph you actually want to look
at is built from wiki pages, not raw dumps.

Distillation itself (deciding what a note means, what its principles are,
what it should link to) is a synthesis task — it happens in the calling
agent, not in this module. This module is the scaffolding Karpathy's setup
gets from Claude Code + a CLAUDE.md schema + git: it validates a distillation
request, writes/updates the page, keeps wiki/index.md and wiki/log.md
current, dedupes by slug so re-distilling a source updates its page instead
of duplicating it, and reindexes so the page is searchable immediately.

No LLM call lives in this module by design — consistent with the rest of the
brain pipeline (see promote.py). Overbuilding a second inference path here
would duplicate what the calling agent already does better.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .index import reindex_sources
from .vault import _FORBIDDEN_CONTENT_PATTERNS, get_vault_path
from .vault import scan_sources as _scan_sources

log = logging.getLogger(__name__)

WIKI_FOLDER = "wiki"
INDEX_FILE = f"{WIKI_FOLDER}/index.md"
LOG_FILE = f"{WIKI_FOLDER}/log.md"

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


def slugify(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:80] or "untitled"


def _redact(text: str) -> str:
    return _FORBIDDEN_CONTENT_PATTERNS.sub("[REDACTED]", text or "")


def _clean_list(items: Optional[list[str]]) -> list[str]:
    return [str(i).strip() for i in (items or []) if str(i).strip()]


def _wiki_dir(vp: Path) -> Path:
    d = vp / WIKI_FOLDER
    d.mkdir(parents=True, exist_ok=True)
    return d


def parse_wikilinks(text: str) -> list[str]:
    """Extract [[Title]] references from markdown text."""
    return list(dict.fromkeys(m.strip() for m in _WIKILINK_RE.findall(text) if m.strip()))


def _render_page(
    *,
    title: str,
    definition: str,
    principles: list[str],
    examples: list[str],
    tags: list[str],
    links: list[str],
    source_path: Optional[str],
    now: str,
) -> str:
    tag_str = ", ".join(tags) if tags else "wiki"
    related_lines = "\n".join(f'  - "[[{l}]]"' for l in links) if links else ""
    fm = (
        "---\n"
        f"title: {title}\n"
        f"tags: {tag_str}\n"
        f"source: {source_path or 'distilled'}\n"
        f"distilled_at: {now}\n"
    )
    if related_lines:
        fm += "related:\n" + related_lines + "\n"
    fm += "---\n\n"

    body = f"# {title}\n\n{_redact(definition).strip()}\n"
    if principles:
        body += "\n## Key Principles\n" + "\n".join(f"- {_redact(p)}" for p in principles) + "\n"
    if examples:
        body += "\n## Examples\n" + "\n".join(f"- {_redact(e)}" for e in examples) + "\n"
    if links:
        body += "\n## Connections\n" + "\n".join(f"- [[{l}]]" for l in links) + "\n"
    if source_path:
        body += f"\n## Source\n`{source_path}`\n"
    return fm + body


def _update_index(vp: Path, title: str, definition: str) -> None:
    idx_path = vp / INDEX_FILE
    one_liner = (definition or "").strip().replace("\n", " ")[:100]
    entry = f"- [[{title}]] — {one_liner}"
    slug_key = title.strip().lower()

    lines: list[str] = []
    if idx_path.exists():
        lines = idx_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    if not lines or not lines[0].startswith("# "):
        lines = ["# Wiki Index", "", "Auto-maintained. One line per wiki page.", ""] + lines

    replaced = False
    out: list[str] = []
    for line in lines:
        m = re.match(r"^- \[\[([^\]]+)\]\]", line)
        if m and m.group(1).strip().lower() == slug_key:
            out.append(entry)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(entry)

    idx_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _append_log(vp: Path, action: str, title: str, source_path: Optional[str], now: str) -> None:
    log_path = vp / LOG_FILE
    if not log_path.exists():
        log_path.write_text("# Wiki Log\n\nChronological record of every distillation.\n\n", encoding="utf-8")
    line = f"- {now} · {action} · [[{title}]]" + (f" · from `{source_path}`" if source_path else "") + "\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


def distill_note(
    *,
    title: str,
    definition: str,
    principles: Optional[list[str]] = None,
    examples: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    links: Optional[list[str]] = None,
    source_path: Optional[str] = None,
    vault_path: Optional[Path] = None,
    index_path=None,
) -> dict:
    """Write (or update) a wiki page distilled from a raw source.

    Called by an agent that has already read the source and synthesized its
    meaning — this function only validates, persists, and wires it into the
    index/log/search index. Re-distilling the same title updates the
    existing page in place instead of creating a duplicate.
    """
    title = (title or "").strip()
    definition = (definition or "").strip()
    if not title:
        raise ValueError("title is required")
    if not definition:
        raise ValueError("definition is required")

    vp = vault_path or get_vault_path()
    wiki_dir = _wiki_dir(vp)

    principles = _clean_list(principles)
    examples = _clean_list(examples)
    tags = _clean_list(tags)
    links = _clean_list(links)

    slug = slugify(title)
    dest = wiki_dir / f"{slug}.md"
    was_update = dest.exists()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    content = _render_page(
        title=title,
        definition=definition,
        principles=principles,
        examples=examples,
        tags=tags,
        links=links,
        source_path=source_path,
        now=now,
    )
    dest.write_text(content, encoding="utf-8")

    _update_index(vp, title, definition)
    _append_log(vp, "updated" if was_update else "created", title, source_path, now)

    sources = _scan_sources(vp)
    reindex_sources(sources, index_path=index_path)

    return {
        "ok": True,
        "created": not was_update,
        "updated": was_update,
        "slug": slug,
        "path": dest.relative_to(vp).as_posix(),
        "title": title,
        "links": links,
        "word_count": len(content.split()),
    }


def list_wiki_pages(vault_path: Optional[Path] = None) -> list[dict]:
    """Return lightweight metadata for every wiki page currently on disk."""
    vp = vault_path or get_vault_path()
    wiki_dir = vp / WIKI_FOLDER
    if not wiki_dir.exists():
        return []
    pages = []
    for p in sorted(wiki_dir.glob("*.md")):
        if p.name in ("index.md", "log.md"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        title_m = re.search(r"^title:\s*(.+)$", text, re.MULTILINE)
        title = title_m.group(1).strip() if title_m else p.stem
        pages.append({
            "slug": p.stem,
            "title": title,
            "path": p.relative_to(vp).as_posix(),
            "links": parse_wikilinks(text),
        })
    return pages
