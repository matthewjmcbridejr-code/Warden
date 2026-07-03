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

def _build_note_body(
    *,
    url: str,
    source_type: str,
    summary: str,
    content: str = "",
    channel: str = "",
    transcript: str = "",
    author: str = "",
) -> str:
    lines = [f"**Source:** {url}", ""]
    if source_type == "youtube":
        if channel:
            lines += [f"**Channel:** {channel}", ""]
    if author:
        lines += [f"**Author:** {author}", ""]
    lines += ["## Summary", "", summary, ""]
    if transcript:
        lines += ["## Transcript (excerpt)", "", transcript[:2000], ""]
    elif content:
        lines += ["## Content", "", content[:2000], ""]
    return "\n".join(lines)


def _stable_filename(url: str, source_type: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    h = hashlib.sha256(url.encode()).hexdigest()[:8]
    slug = re.sub(r"[^\w]", "-", urllib.parse.urlparse(url).netloc + urllib.parse.urlparse(url).path)[:40]
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"{source_type}-{slug}-{h}-{ts}.md"


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
    body = _build_note_body(
        url=url,
        source_type=source_type,
        summary=summary,
        content=content_text if source_type not in ("youtube",) else "",
    )

    filename = _stable_filename(url, source_type)
    try:
        result = write_note(
            title=title,
            body=body,
            tags=all_tags,
            filename=filename,
            vault_path=vp,
        )
    except FileExistsError:
        return {"ok": False, "error": "Already saved", "url": url}

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
    body = _build_note_body(
        url=url,
        source_type="youtube",
        summary=summary,
        channel=channel,
        transcript=transcript,
    )

    try:
        result = write_note(title=f"[Video] {title}", body=body, tags=all_tags, filename=filename, vault_path=vp)
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


def _extract_pdf_text(url: str, max_chars: int = 8000) -> str:
    """Download PDF and extract text. Returns empty string on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WardenBrain/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            pdf_bytes = resp.read()
    except Exception as exc:
        log.warning("PDF download failed for %s: %s", url, exc)
        return ""

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
