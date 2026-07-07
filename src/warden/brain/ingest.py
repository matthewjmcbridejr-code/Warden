"""Warden Brain ingest — capture webpages, YouTube, PDFs, selected text into the vault.

Write Markdown → reindex → optionally mirror to Google Brain.
Summarization: extractive first, Ollama optional.
No paid services required for the basic flow.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .vault import write_note, get_vault_path, get_write_folder, init_vault
from .index import reindex_sources
from .vault import scan_sources

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple extractive summarizer (no LLM required)
# ---------------------------------------------------------------------------

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _extractive_summary(text: str, max_chars: int = 500) -> str:
    """Return first N chars of clean text as an extractive summary."""
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= max_chars:
        return clean
    # Try to end at a sentence boundary
    sentences = SENTENCE_END.split(clean[:max_chars + 200])
    out = ""
    for s in sentences:
        if len(out) + len(s) > max_chars:
            break
        out += s + " "
    return out.strip() or clean[:max_chars] + "…"


def _ollama_summarize(text: str, title: str) -> Optional[str]:
    """Try Ollama for a better summary. Returns None if unavailable."""
    try:
        import httpx
        model = os.getenv("WARDEN_EMBED_MODEL", "qwen3:0.6b")
        # Use a chat model if embed model is not a chat model
        chat_model = os.getenv("WARDEN_SUMMARIZE_MODEL", "qwen3:0.6b")
        payload = {
            "model": chat_model,
            "prompt": (
                f"Summarize the following content from '{title}' in 3-5 sentences. "
                f"Focus on key facts, decisions, and insights. Be concise.\n\n"
                f"{text[:3000]}"
            ),
            "stream": False,
        }
        resp = httpx.post(
            f"{os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434')}/api/generate",
            json=payload,
            timeout=20.0,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip() or None
    except Exception as exc:
        log.debug("Ollama summarize unavailable: %s", exc)
        return None


def _summarize(text: str, title: str) -> str:
    ollama_result = _ollama_summarize(text, title)
    return ollama_result or _extractive_summary(text)


# ---------------------------------------------------------------------------
# Tag inference
# ---------------------------------------------------------------------------

TAG_RULES: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"youtube\.com|youtu\.be", re.I), ["video", "youtube"]),
    (re.compile(r"github\.com", re.I), ["github", "code"]),
    (re.compile(r"arxiv\.org", re.I), ["research", "paper"]),
    (re.compile(r"news|blog|medium\.com|substack\.com", re.I), ["article"]),
    (re.compile(r"\.pdf$|/pdf/", re.I), ["pdf", "document"]),
    (re.compile(r"docs\.|documentation|readthedocs", re.I), ["docs"]),
    (re.compile(r"stackoverflow\.com", re.I), ["stackoverflow", "code"]),
    (re.compile(r"reddit\.com", re.I), ["reddit"]),
    (re.compile(r"twitter\.com|x\.com", re.I), ["social"]),
]


def _infer_tags(url: str, source_type: str, extra: Optional[list[str]] = None) -> list[str]:
    tags = set(["watcher", source_type])
    for pattern, t in TAG_RULES:
        if pattern.search(url):
            tags.update(t)
    if extra:
        tags.update(extra)
    return sorted(tags)


# ---------------------------------------------------------------------------
# Markdown note builder
# ---------------------------------------------------------------------------

# Bounded raw content stored in vault notes. Raised from the old 2,000-char excerpt
# (personal_ai_os_plan PR 3): anything past this is flagged, never silently dropped.
RAW_NOTE_CONTENT_MAX = 20000


def _build_note_body(
    *,
    url: str,
    source_type: str,
    summary: str,
    content: str = "",
    channel: str = "",
    transcript: str = "",
    author: str = "",
) -> tuple[str, bool]:
    """Build the note body. Returns (body, raw_content_truncated)."""
    truncated = False
    lines = [f"**Source:** {url}", ""]
    if source_type == "youtube":
        if channel:
            lines += [f"**Channel:** {channel}", ""]
    if author:
        lines += [f"**Author:** {author}", ""]
    lines += ["## Summary", "", summary, ""]
    if transcript:
        truncated = len(transcript) > RAW_NOTE_CONTENT_MAX
        lines += ["## Transcript", "", transcript[:RAW_NOTE_CONTENT_MAX], ""]
    elif content:
        truncated = len(content) > RAW_NOTE_CONTENT_MAX
        lines += ["## Content", "", content[:RAW_NOTE_CONTENT_MAX], ""]
    if truncated:
        lines += [f"> Source content truncated at {RAW_NOTE_CONTENT_MAX} characters.", ""]
    return "\n".join(lines), truncated


def _stable_filename(url: str, source_type: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    h = hashlib.sha256(url.encode()).hexdigest()[:8]
    slug = re.sub(r"[^\w]", "-", urllib.parse.urlparse(url).netloc + urllib.parse.urlparse(url).path)[:40]
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"{source_type}-{slug}-{h}-{ts}.md"


# ---------------------------------------------------------------------------
# Linking (personal_ai_os_plan PR 4): vault index + tag-based related notes
# ---------------------------------------------------------------------------

_GENERIC_TAGS = {"watcher", "auto", "warden", "webpage", "selection", "pdf", "youtube", "manual"}


def _related_notes_section(vault_path, tags: list[str], limit: int = 5) -> str:
    """Return a '## Related' markdown section linking existing notes that share a
    non-generic tag with this capture. Empty string when nothing relates."""
    specific = [t for t in tags if t not in _GENERIC_TAGS]
    if not specific:
        return ""
    try:
        related: list[str] = []
        for path in sorted(vault_path.rglob("*.md"), reverse=True):
            if len(related) >= limit:
                break
            if path.name == "00-index.md":
                continue
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:600]
            except OSError:
                continue
            match = re.search(r"^tags:\s*(.+)$", head, re.MULTILINE)
            if not match:
                continue
            note_tags = {t.strip() for t in match.group(1).split(",")}
            if note_tags.intersection(specific):
                related.append(f"- [[{path.stem}]]")
        if not related:
            return ""
        return "\n## Related\n\n" + "\n".join(related) + "\n"
    except Exception:
        return ""


def _append_vault_index(vault_path, *, title: str, note_path: str, tags: list[str]) -> None:
    """Append this capture to the vault's 00-index.md (lightweight backlink index)."""
    try:
        index = vault_path / "00-index.md"
        if not index.exists():
            index.write_text("# Vault index\n\n", encoding="utf-8")
        stem = Path(note_path).stem
        tag_str = ", ".join(t for t in tags if t not in _GENERIC_TAGS) or "-"
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with index.open("a", encoding="utf-8") as f:
            f.write(f"- {stamp} [[{stem}]] — {title} ({tag_str})\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Core ingest function
# ---------------------------------------------------------------------------

def _do_ingest(
    *,
    url: str,
    title: str,
    source_type: str,
    content_text: str,
    tags: Optional[list[str]] = None,
    vault_path=None,
    index_path=None,
    local_only: bool = False,
    extra_frontmatter: Optional[dict] = None,
) -> dict:
    vp = vault_path or get_vault_path()
    if not vp.exists():
        init_vault(vp)

    summary = _summarize(content_text, title)
    all_tags = _infer_tags(url, source_type, tags)
    body, raw_truncated = _build_note_body(
        url=url,
        source_type=source_type,
        summary=summary,
        content=content_text if source_type not in ("youtube",) else "",
    )
    body += _related_notes_section(vp, all_tags)

    filename = _stable_filename(url, source_type)
    frontmatter = {
        "url": url,
        "raw_content_truncated": str(raw_truncated).lower(),
        **(extra_frontmatter or {}),
    }
    try:
        result = write_note(
            title=title,
            body=body,
            tags=all_tags,
            filename=filename,
            vault_path=vp,
            extra_frontmatter=frontmatter,
        )
    except FileExistsError:
        return {"ok": False, "error": "Already saved", "url": url}

    _append_vault_index(vp, title=title, note_path=result.get("path", ""), tags=all_tags)

    # Reindex
    sources = scan_sources(vp)
    reindex_sources(sources, index_path=index_path)

    # Mirror to Google if enabled and not local-only
    mirror_result = None
    if not local_only:
        try:
            from . import google_provider
            from .mirror import mirror_sources as do_mirror
            if google_provider.is_enabled() and google_provider.is_configured():
                # Find the new source by path
                new_path = result.get("path", "")
                matching = [s for s in sources if s.path == new_path]
                if matching:
                    mirror_result = do_mirror(
                        source_ids=[matching[0].source_id],
                        dry_run=False,
                        vault_path=vp,
                        index_path=index_path,
                    )
        except Exception as exc:
            log.warning("Google mirror failed: %s", exc)
            mirror_result = {"error": str(exc)}

    return {
        "ok": True,
        "url": url,
        "title": title,
        "source_type": source_type,
        "note_path": result.get("path"),
        "summary": summary,
        "tags": all_tags,
        "word_count": result.get("word_count", 0),
        "raw_content_truncated": raw_truncated,
        "mirrored": mirror_result,
    }


# ---------------------------------------------------------------------------
# Public ingest entrypoints
# ---------------------------------------------------------------------------

def ingest_webpage(
    url: str,
    title: str,
    content_text: str,
    selected_text: str = "",
    tags: Optional[list[str]] = None,
    vault_path=None,
    index_path=None,
    local_only: bool = False,
) -> dict:
    """Save a webpage into the Brain vault."""
    text = selected_text or content_text
    return _do_ingest(
        url=url,
        title=title,
        source_type="webpage",
        content_text=text,
        tags=tags,
        vault_path=vault_path,
        index_path=index_path,
        local_only=local_only,
    )


def ingest_selection(
    url: str,
    title: str,
    selected_text: str,
    tags: Optional[list[str]] = None,
    vault_path=None,
    index_path=None,
    local_only: bool = False,
) -> dict:
    """Save selected text into the Brain vault."""
    return _do_ingest(
        url=url,
        title=f"Selection: {title}",
        source_type="selection",
        content_text=selected_text,
        tags=(tags or []) + ["selection"],
        vault_path=vault_path,
        index_path=index_path,
        local_only=local_only,
    )


def ingest_youtube(
    url: str,
    title: str,
    channel: str = "",
    description: str = "",
    transcript: str = "",
    tags: Optional[list[str]] = None,
    vault_path=None,
    index_path=None,
    local_only: bool = False,
) -> dict:
    """Save a YouTube video (with transcript if available) into the Brain vault."""
    combined = " ".join(filter(None, [description, transcript]))
    vp = vault_path or get_vault_path()
    if not vp.exists():
        init_vault(vp)

    summary = _summarize(combined or title, title)
    all_tags = _infer_tags(url, "youtube", tags)
    filename = _stable_filename(url, "youtube")
    body, yt_truncated = _build_note_body(
        url=url,
        source_type="youtube",
        summary=summary,
        channel=channel,
        transcript=transcript,
    )

    try:
        result = write_note(
            title=f"[Video] {title}", body=body, tags=all_tags, filename=filename, vault_path=vp,
            extra_frontmatter={"url": url, "raw_content_truncated": str(yt_truncated).lower()},
        )
    except FileExistsError:
        return {"ok": False, "error": "Already saved", "url": url}

    sources = scan_sources(vp)
    reindex_sources(sources, index_path=index_path)

    mirror_result = None
    if not local_only:
        try:
            from . import google_provider
            from .mirror import mirror_sources as do_mirror
            if google_provider.is_enabled() and google_provider.is_configured():
                new_path = result.get("path", "")
                matching = [s for s in sources if s.path == new_path]
                if matching:
                    mirror_result = do_mirror(source_ids=[matching[0].source_id], dry_run=False, vault_path=vp, index_path=index_path)
        except Exception as exc:
            log.warning("Google mirror failed: %s", exc)
            mirror_result = {"error": str(exc)}

    return {
        "ok": True,
        "url": url,
        "title": title,
        "source_type": "youtube",
        "note_path": result.get("path"),
        "summary": summary,
        "tags": all_tags,
        "transcript_chars": len(transcript),
        "mirrored": mirror_result,
    }


def ingest_pdf(
    url: str,
    title: str = "",
    tags: Optional[list[str]] = None,
    vault_path=None,
    index_path=None,
    local_only: bool = False,
) -> dict:
    """Download and extract text from a PDF URL, save to Brain vault."""
    # Try to extract text
    text = _extract_pdf_text(url)
    if not text:
        text = f"PDF from {url} — text extraction failed or PDF is image-only."

    display_title = title or _pdf_title_from_url(url)
    return _do_ingest(
        url=url,
        title=display_title,
        source_type="pdf",
        content_text=text,
        tags=(tags or []) + ["pdf"],
        vault_path=vault_path,
        index_path=index_path,
        local_only=local_only,
    )


def _pdf_title_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    name = path.split("/")[-1]
    return re.sub(r"[_-]+", " ", name.replace(".pdf", "")).strip() or "PDF Document"


def _extract_pdf_text_from_bytes(pdf_bytes: bytes, max_chars: int = 8000) -> str:
    """Extract text from raw PDF bytes. Returns empty string on failure."""
    # Try pypdf first
    try:
        import pypdf
        import io
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages_text = []
        for page in reader.pages:
            pt = page.extract_text() or ""
            pages_text.append(pt)
            if sum(len(t) for t in pages_text) > max_chars:
                break
        return " ".join(pages_text)[:max_chars]
    except ImportError:
        pass
    except Exception as exc:
        log.warning("pypdf extraction failed: %s", exc)

    # Try PyMuPDF (fitz)
    try:
        import fitz  # type: ignore
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
            if sum(len(t) for t in text_parts) > max_chars:
                break
        return " ".join(text_parts)[:max_chars]
    except ImportError:
        pass
    except Exception as exc:
        log.warning("PyMuPDF extraction failed: %s", exc)

    return ""


def _extract_pdf_text(url: str, max_chars: int = 8000) -> str:
    """Download PDF and extract text. Returns empty string on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WardenBrain/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            pdf_bytes = resp.read()
    except Exception as exc:
        log.warning("PDF download failed for %s: %s", url, exc)
        return ""

    return _extract_pdf_text_from_bytes(pdf_bytes, max_chars=max_chars)


# ---------------------------------------------------------------------------
# YouTube transcript fetcher
# ---------------------------------------------------------------------------

def fetch_youtube_transcript(url: str) -> dict:
    """Fetch YouTube transcript and metadata. Returns {title, channel, transcript, error}."""
    video_id = _extract_youtube_id(url)
    if not video_id:
        return {"error": "Could not extract YouTube video ID from URL"}

    result: dict = {"video_id": video_id, "url": url}

    # Try youtube-transcript-api
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        transcript_text = " ".join(t["text"] for t in transcript_list)
        result["transcript"] = transcript_text
        result["transcript_chars"] = len(transcript_text)
    except ImportError:
        result["transcript"] = ""
        result["transcript_error"] = "youtube-transcript-api not installed. Run: pip install youtube-transcript-api"
    except Exception as exc:
        result["transcript"] = ""
        result["transcript_error"] = str(exc)

    return result


def _extract_youtube_id(url: str) -> Optional[str]:
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Generic ingest (warden_ingest MCP tool) — honest, deduped, always searchable
# ---------------------------------------------------------------------------
#
# This is the path used by warden_ingest for arbitrary text/file ingestion
# (Obsidian notes, repo docs, agent proofs, manual saves). Earlier this tool
# delegated to src.marius.brain_ingest.BrainIngest, which writes to a
# completely separate JSONL store (~/.local/share/marius/brain/records.jsonl)
# that brain_search/brain_reindex/brain_list_sources never read — so ingest
# returned ok:true for writes that were never actually searchable. This path
# writes through the same vault + SQLite index that backs search, so a
# successful response is provably true.

GENERIC_SOURCE_TYPES = {"obsidian", "repo", "manual", "agent_proof", "doc"}


def normalize_content_for_hash(text: str) -> str:
    """Collapse whitespace so near-identical captures hash the same."""
    return re.sub(r"\s+", " ", text).strip().lower()


def compute_content_hash(text: str) -> str:
    return hashlib.sha256(normalize_content_for_hash(text).encode()).hexdigest()


def _frontmatter_field(text: str, key: str) -> str:
    """Read a single frontmatter field without pulling in the full vault parser."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    block = text[3:end]
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", block, re.MULTILINE)
    return m.group(1).strip() if m else ""


def find_duplicate_by_content_hash(vault_path: Path, content_hash: str) -> Optional[dict]:
    """Scan the vault's Markdown files for one whose content_hash frontmatter matches.

    O(n) over vault files by design — this is a personal vault (tens to low
    hundreds of notes), not a search index, so no schema migration is needed
    to get honest dedupe.
    """
    if not vault_path.exists():
        return None
    for p in sorted(vault_path.rglob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _frontmatter_field(text, "content_hash") == content_hash:
            title = _frontmatter_field(text, "title") or p.stem
            return {"path": p.relative_to(vault_path).as_posix(), "title": title}
    return None


def ingest_generic(
    *,
    text: str,
    title: str,
    source_type: str,
    project: str = "",
    tags: Optional[list[str]] = None,
    vault_path=None,
    index_path=None,
) -> dict:
    """Ingest arbitrary text/file content into the real Warden Brain vault + index.

    Always honest: if this returns ok=True and duplicate=False, the note was
    written to disk, scanned, and reindexed into the SQLite FTS index used by
    brain_search — i.e. it is actually searchable, not just claimed to be.
    """
    if source_type not in GENERIC_SOURCE_TYPES:
        return {
            "ok": False,
            "error": f"Unknown source_type {source_type!r}; must be one of {sorted(GENERIC_SOURCE_TYPES)}",
        }
    if not text or not text.strip():
        return {"ok": False, "error": "No content to ingest"}

    vp = vault_path or get_vault_path()
    if not vp.exists():
        init_vault(vp)

    content_hash = compute_content_hash(text)
    dup = find_duplicate_by_content_hash(vp, content_hash)
    if dup:
        return {
            "ok": True,
            "ingested": False,
            "duplicate": True,
            "duplicate_of": dup["path"],
            "title": dup["title"],
        }

    all_tags = sorted(set((tags or []) + [f"source_{source_type}"]))
    frontmatter = {"content_hash": content_hash, "source_type": source_type}
    if project:
        frontmatter["project"] = project

    try:
        result = write_note(
            title=title,
            body=text,
            tags=all_tags,
            vault_path=vp,
            extra_frontmatter=frontmatter,
        )
    except FileExistsError as exc:
        return {"ok": False, "error": str(exc)}
    except ValueError as exc:
        return {"ok": False, "error": f"Invalid note: {exc}"}

    sources = scan_sources(vp)
    reindex_result = reindex_sources(sources, index_path=index_path)
    new_source = next((s for s in sources if s.path == result["path"]), None)
    if new_source is None:
        # Should be unreachable — write_note succeeded but scan_sources didn't
        # pick it up. Surface as a real failure instead of a false ok:true.
        return {"ok": False, "error": "Note written but not found by scan_sources; index inconsistent"}

    return {
        "ok": True,
        "ingested": True,
        "duplicate": False,
        "source_id": new_source.source_id,
        "path": result["path"],
        "title": title,
        "word_count": result.get("word_count", 0),
        "reindex": reindex_result,
    }


# ---------------------------------------------------------------------------
# Obsidian vault import — read-only against the source vault
# ---------------------------------------------------------------------------

def import_obsidian_vault(
    obsidian_path,
    *,
    vault_path=None,
    index_path=None,
    limit: Optional[int] = None,
) -> dict:
    """Copy Markdown notes from an external Obsidian vault into Warden Brain.

    Never writes to obsidian_path — read-only against the source. Each
    imported note is deduped by content hash and tagged 'obsidian-vault' plus
    'source_obsidian' so it's identifiable in search/list results.
    """
    src_vp = Path(obsidian_path).expanduser()
    if not src_vp.exists():
        return {"ok": False, "error": f"Obsidian vault not found: {src_vp}"}

    vp = vault_path or get_vault_path()
    if not vp.exists():
        init_vault(vp)

    imported: list[dict] = []
    duplicates: list[dict] = []
    errors: list[dict] = []

    md_files = sorted(
        p for p in src_vp.rglob("*.md")
        if ".obsidian" not in p.parts and ".trash" not in p.parts
    )
    if limit:
        md_files = md_files[:limit]

    for p in md_files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            errors.append({"path": str(p), "error": str(exc)})
            continue

        result = ingest_generic(
            text=text,
            title=p.stem,
            source_type="obsidian",
            tags=["obsidian-vault"],
            vault_path=vp,
            index_path=index_path,
        )
        if not result.get("ok"):
            errors.append({"path": str(p), "error": result.get("error", "unknown error")})
        elif result.get("duplicate"):
            duplicates.append({"path": str(p), "duplicate_of": result.get("duplicate_of")})
        else:
            imported.append({"path": str(p), "note_path": result.get("path"), "source_id": result.get("source_id")})

    return {
        "ok": True,
        "scanned": len(md_files),
        "imported": len(imported),
        "duplicates": len(duplicates),
        "errors": len(errors),
        "imported_notes": imported,
        "duplicate_notes": duplicates,
        "error_notes": errors,
    }
