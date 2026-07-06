"""Warden Brain dropzone — a folder the user drops files into for automatic
sorting and indexing into the Brain vault.

Flow: file lands in the dropzone -> classified (project, private/financial,
secret-suspected) -> text extracted (bounded) -> vault note written -> the
original file is moved into dropzone/sorted/<project>/ (kept, not deleted).
Secret-suspected files (credentials, tokens, key files) are never read or
indexed; they are left in place and reported as skipped.

See docs/personal_ai_os_plan.md for the wider capture/distill/link loop this
fits into.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from .ingest import _extract_pdf_text_from_bytes, _summarize
from .vault import get_vault_path, init_vault, scan_sources, write_note
from .index import reindex_sources

log = logging.getLogger(__name__)

DEFAULT_DROPZONE_PATH = Path.home() / "warden-drop"
SORTED_SUBDIR = "sorted"

TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".html", ".htm", ".json"}
PDF_EXTENSIONS = {".pdf"}
MAX_CONTENT_CHARS = 4000

FINANCIAL_PATTERNS = re.compile(
    r"statement|receipt|invoice|\bbill\b|transhistory|bank|paystub|payroll|"
    r"\btax\b|1099|w-?2|\bnod\b",
    re.IGNORECASE,
)

# Filenames that suggest credentials/secrets — never read or indexed.
SECRET_FILENAME_PATTERNS = re.compile(
    r"client[-_]?secret|credentials?|service[-_]?account|\.pem$|\.key$|\.env(\.|$)|"
    r"\btoken\b|api[-_]?key",
    re.IGNORECASE,
)

PROJECT_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"warden|mcharness|marius", re.IGNORECASE), "warden"),
    (re.compile(r"grademy|shelf\.?report", re.IGNORECASE), "grademy"),
    (re.compile(r"slosar|client work", re.IGNORECASE), "client-work"),
    (re.compile(r"upwork", re.IGNORECASE), "upwork"),
    (re.compile(r"vegas|sales lead", re.IGNORECASE), "sales-leads"),
    (re.compile(r"hermes", re.IGNORECASE), "hermes"),
    (re.compile(r"fable ?5", re.IGNORECASE), "fable5"),
    (re.compile(r"resume|cover letter|job search|\bey\b", re.IGNORECASE), "job-search"),
]

DEFAULT_PROJECT = "personal"


def get_dropzone_path() -> Path:
    raw = os.getenv("WARDEN_DROPZONE_PATH", "")
    return Path(raw).expanduser() if raw else DEFAULT_DROPZONE_PATH


def ensure_dropzone(path: Optional[Path] = None) -> Path:
    dz = path or get_dropzone_path()
    dz.mkdir(parents=True, exist_ok=True)
    (dz / SORTED_SUBDIR).mkdir(parents=True, exist_ok=True)
    return dz


def _detect_project(name: str, text: str) -> str:
    haystack = f"{name} {text[:500]}"
    for pattern, project in PROJECT_RULES:
        if pattern.search(haystack):
            return project
    return DEFAULT_PROJECT


def _is_secret_suspect(path: Path) -> bool:
    return bool(SECRET_FILENAME_PATTERNS.search(path.name))


def _is_financial(path: Path) -> bool:
    return bool(FINANCIAL_PATTERNS.search(path.name))


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_EXTENSIONS:
            return path.read_text(encoding="utf-8", errors="replace")[:MAX_CONTENT_CHARS]
        if suffix in PDF_EXTENSIONS:
            return _extract_pdf_text_from_bytes(path.read_bytes(), max_chars=MAX_CONTENT_CHARS)
    except Exception as exc:
        log.warning("Dropzone text extraction failed for %s: %s", path, exc)
    return ""


def sort_drop_folder(
    *,
    dropzone_path: Optional[Path] = None,
    vault_path: Optional[Path] = None,
    index_path=None,
    dry_run: bool = False,
) -> dict:
    """Scan the dropzone's top level, sort each file into the vault, and move
    the original into dropzone/sorted/<project>/. Never recurses into
    dropzone/sorted/ itself, so already-processed files are not reprocessed.
    """
    dz = ensure_dropzone(dropzone_path)
    vp = vault_path or get_vault_path()
    if not vp.exists():
        init_vault(vp)

    results: dict = {"ok": True, "dry_run": dry_run, "processed": [], "skipped": []}

    for entry in sorted(dz.iterdir()):
        if entry.is_dir() or entry.name.startswith("."):
            continue
        if _is_secret_suspect(entry):
            results["skipped"].append({"file": entry.name, "reason": "secret-suspected"})
            continue

        text = _extract_text(entry)
        project = _detect_project(entry.name, text)
        private = _is_financial(entry)
        title = re.sub(r"[_-]+", " ", entry.stem).strip() or entry.name

        if dry_run:
            results["processed"].append({
                "file": entry.name, "project": project, "private": private, "title": title,
            })
            continue

        summary = _summarize(text, title) if text else f"Dropzone file (no extractable text): {entry.name}"
        lines = [f"**Original file:** {entry.name}", "", "## Summary", "", summary, ""]
        if text:
            lines += ["## Content", "", text[:2000], ""]
        body = "\n".join(lines)

        tags = ["dropzone", project]
        if private:
            tags.append("private")

        try:
            note_result = write_note(
                title=title,
                body=body,
                tags=tags,
                vault_path=vp,
                extra_frontmatter={"dropzone_source": entry.name, "private": str(private).lower()},
            )
        except FileExistsError:
            results["skipped"].append({"file": entry.name, "reason": "note already exists"})
            continue
        except Exception as exc:
            results["skipped"].append({"file": entry.name, "reason": str(exc)})
            continue

        sorted_dir = dz / SORTED_SUBDIR / project
        sorted_dir.mkdir(parents=True, exist_ok=True)
        dest = sorted_dir / entry.name
        try:
            shutil.move(str(entry), str(dest))
        except Exception as exc:
            log.warning("Could not move %s into %s: %s", entry, sorted_dir, exc)
            dest = entry

        results["processed"].append({
            "file": entry.name,
            "project": project,
            "private": private,
            "title": title,
            "note_path": note_result.get("path"),
            "sorted_to": str(dest),
        })

    if not dry_run and results["processed"]:
        sources = scan_sources(vp)
        reindex_sources(sources, index_path=index_path)

    return results
